"""Provider-neutral qualification for an already-authorized RATE intraday payload.

No network access, credential handling, provider selection, registry activation or
Production publication occurs here. This module validates an input contract only.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import math
from typing import Any, Mapping
TAIPEI = timezone(timedelta(hours=8), name="Asia/Taipei")
CADENCES = {"09:30", "12:00"}
REQUIRED_FIELDS = ("symbol", "market", "timestamp", "price", "volume", "turnover")
ALLOWED_MARKETS = {"TWSE", "TPEX"}


class IntradayQualificationError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise IntradayQualificationError(reason)


def _timestamp(value: Any) -> datetime:
    require(isinstance(value, str) and value.strip(), "INTRADAY_TIMESTAMP_MISSING")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IntradayQualificationError("INTRADAY_TIMESTAMP_INVALID") from exc
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None, "INTRADAY_TIMESTAMP_TIMEZONE_REQUIRED")
    return parsed.astimezone(timezone.utc)


def _number(value: Any, *, positive: bool) -> float:
    require(not isinstance(value, bool) and isinstance(value, (int, float)), "INTRADAY_NUMERIC_INVALID")
    number = float(value)
    require(math.isfinite(number), "INTRADAY_NUMERIC_INVALID")
    require(number > 0 if positive else number >= 0, "INTRADAY_NUMERIC_INVALID")
    return number


def _expected_universe(expected_universe: Mapping[str, str]) -> dict[str, str]:
    require(isinstance(expected_universe, Mapping), "INTRADAY_EXPECTED_UNIVERSE_INVALID")
    normalized = {str(symbol).strip(): str(market).strip().upper() for symbol, market in expected_universe.items()}
    require(len(normalized) == 30 and all(normalized), "INTRADAY_EXPECTED_UNIVERSE_COUNT_INVALID")
    require(set(normalized.values()).issubset(ALLOWED_MARKETS), "INTRADAY_EXPECTED_MARKET_INVALID")
    require(set(normalized.values()) == ALLOWED_MARKETS, "INTRADAY_DUAL_MARKET_COVERAGE_REQUIRED")
    return normalized


def qualify_authorized_intraday_payload(
    payload: Mapping[str, Any],
    *,
    expected_universe: Mapping[str, str],
    trading_date: str,
    cadence: str,
    now_utc: datetime,
    max_age_seconds: int = 180,
) -> dict[str, Any]:
    require(cadence in CADENCES, "INTRADAY_CADENCE_INVALID")
    require(isinstance(max_age_seconds, int) and max_age_seconds > 0, "INTRADAY_FRESHNESS_LIMIT_INVALID")
    require(now_utc.tzinfo is not None and now_utc.utcoffset() is not None, "INTRADAY_NOW_TIMEZONE_REQUIRED")
    try:
        datetime.fromisoformat(trading_date)
    except ValueError as exc:
        raise IntradayQualificationError("INTRADAY_TRADING_DATE_INVALID") from exc

    expected = _expected_universe(expected_universe)
    require(isinstance(payload, Mapping), "INTRADAY_PAYLOAD_INVALID")
    require(payload.get("artifact") == "RATE_AUTHORIZED_TAIWAN_INTRADAY_FEED_V1", "INTRADAY_ARTIFACT_INVALID")
    require(payload.get("authorization_status") == "PASS", "INTRADAY_AUTHORIZATION_NOT_PASS")
    require(payload.get("validation_status") == "PASS", "INTRADAY_PROVIDER_VALIDATION_NOT_PASS")
    require(payload.get("fallback_used") is False, "INTRADAY_FALLBACK_FORBIDDEN")
    require(payload.get("trading_date") == trading_date and payload.get("cadence") == cadence,
            "INTRADAY_SCOPE_BINDING_MISMATCH")
    require(isinstance(payload.get("provider_authority"), str) and payload["provider_authority"].strip(),
            "INTRADAY_PROVIDER_AUTHORITY_MISSING")

    license_scope = payload.get("license_scope")
    require(isinstance(license_scope, Mapping)
            and license_scope.get("automated_production_use") is True,
            "INTRADAY_AUTOMATED_USE_AUTHORITY_REQUIRED")
    licensed_markets = {str(v).upper() for v in license_scope.get("markets", [])}
    require(ALLOWED_MARKETS.issubset(licensed_markets), "INTRADAY_LICENSE_MARKET_COVERAGE_INCOMPLETE")

    records = payload.get("records")
    require(isinstance(records, list) and records, "INTRADAY_RECORDS_MISSING")
    by_symbol: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for index, row in enumerate(records):
        require(isinstance(row, Mapping), "INTRADAY_ROW_NOT_OBJECT")
        missing = [field for field in REQUIRED_FIELDS if field not in row]
        require(not missing, "INTRADAY_ROW_SCHEMA_MISSING:" + ",".join(missing))
        symbol = str(row["symbol"]).strip()
        market = str(row["market"]).strip().upper()
        require(symbol and market in ALLOWED_MARKETS, "INTRADAY_ROW_IDENTITY_INVALID")
        if symbol in by_symbol:
            duplicates.append(symbol)
            continue
        stamp = _timestamp(row["timestamp"])
        require(stamp.astimezone(TAIPEI).date().isoformat() == trading_date,
                "INTRADAY_TIMESTAMP_TRADING_DATE_MISMATCH")
        age = (now_utc.astimezone(timezone.utc) - stamp).total_seconds()
        require(0 <= age <= max_age_seconds, "INTRADAY_FRESHNESS_FAIL")
        normalized = {
            "symbol": symbol,
            "market": market,
            "timestamp_utc": stamp.isoformat(),
            "age_seconds": age,
            "price": _number(row["price"], positive=True),
            "volume": _number(row["volume"], positive=False),
            "turnover": _number(row["turnover"], positive=False),
        }
        by_symbol[symbol] = normalized
    require(not duplicates, "INTRADAY_DUPLICATE_SYMBOL:" + ",".join(sorted(set(duplicates))))

    selected: dict[str, dict[str, Any]] = {}
    missing_symbols: list[str] = []
    market_mismatches: list[str] = []
    for symbol, expected_market in expected.items():
        row = by_symbol.get(symbol)
        if row is None:
            missing_symbols.append(symbol)
        elif row["market"] != expected_market:
            market_mismatches.append(symbol)
        else:
            selected[symbol] = row

    require(not missing_symbols, "INTRADAY_EXPECTED_SYMBOL_MISSING:" + ",".join(sorted(missing_symbols)))
    require(not market_mismatches, "INTRADAY_MARKET_BINDING_MISMATCH:" + ",".join(sorted(market_mismatches)))

    actual_market_counts = dict(Counter(row["market"] for row in selected.values()))
    expected_market_counts = dict(Counter(expected.values()))
    require(actual_market_counts == expected_market_counts, "INTRADAY_MARKET_COVERAGE_MISMATCH")

    extras = sorted(set(by_symbol) - set(expected))
    freshest = min(row["timestamp_utc"] for row in selected.values())
    oldest_age = max(row["age_seconds"] for row in selected.values())
    return {
        "artifact": "RATE_AUTHORIZED_TAIWAN_INTRADAY_PAYLOAD_QUALIFICATION_V1",
        "validation_status": "PASS",
        "authorization_status": "INPUT_ASSERTED_PASS_NOT_ACTIVATED_BY_THIS_MODULE",
        "provider_authority": payload["provider_authority"],
        "trading_date": trading_date,
        "cadence": cadence,
        "expected_count": len(expected),
        "selected_count": len(selected),
        "coverage": f"{len(selected)}/{len(expected)}",
        "expected_market_counts": expected_market_counts,
        "selected_market_counts": actual_market_counts,
        "required_markets": sorted(ALLOWED_MARKETS),
        "licensed_markets": sorted(licensed_markets),
        "extra_raw_symbols": extras,
        "extra_raw_symbol_policy": "ALLOWED_NOT_SELECTED",
        "oldest_age_seconds": oldest_age,
        "earliest_selected_timestamp_utc": freshest,
        "fallback_used": False,
        "network_requests": 0,
        "credential_access": 0,
        "provider_selected_by_module": False,
        "registry_activated": False,
        "production_eligible": False,
        "production_admission_status": "SEPARATE_CONTROL_CENTER_AND_REGISTRY_ACTIVATION_REQUIRED",
    }

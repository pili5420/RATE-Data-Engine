"""Fugle free/basic intraday feasibility diagnostic for RATE V11.

This module never changes Production registry or resolves the external dependency.
It performs at most one REST quote request per bound symbol, with no retry.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import math
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = "https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/"
MAX_REQUESTS = 30
MAX_AGE_SECONDS = 180


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
    if text == "TPEX":
        return "TPEX"
    if text == "TWSE":
        return "TWSE"
    raise FugleDiagnosticError("FUGLE_MARKET_INVALID:" + text)


def _request(symbol: str, api_key: str, opener=urlopen) -> Mapping[str, Any]:
    require(api_key, "FUGLE_API_KEY_MISSING")
    req = Request(BASE_URL + symbol, headers={"X-API-KEY": api_key, "Accept": "application/json"})
    try:
        response = opener(req, timeout=10)
        status = getattr(response, "status", 200)
        body = response.read()
    except HTTPError as exc:
        if exc.code == 403:
            raise FugleDiagnosticError("FUGLE_FREE_PLAN_NOT_AUTHORIZED") from exc
        if exc.code == 429:
            raise FugleDiagnosticError("FUGLE_FREE_PLAN_RATE_LIMIT") from exc
        if exc.code == 401:
            raise FugleDiagnosticError("FUGLE_API_KEY_INVALID") from exc
        raise FugleDiagnosticError("FUGLE_HTTP_" + str(exc.code)) from exc
    except URLError as exc:
        raise FugleDiagnosticError("FUGLE_CONNECTIVITY_FAILURE") from exc
    require(status == 200 and body, "FUGLE_HTTP_OR_EMPTY_RESPONSE")
    try:
        value = json.loads(body)
    except json.JSONDecodeError as exc:
        raise FugleDiagnosticError("FUGLE_NON_JSON_RESPONSE") from exc
    require(isinstance(value, Mapping), "FUGLE_RESPONSE_NOT_OBJECT")
    return value


def load_binding(value: Mapping[str, Any]) -> dict[str, str]:
    require(value.get("validation_status") == "PASS", "FUGLE_BINDING_NOT_PASS")
    records = value.get("records")
    require(isinstance(records, list) and len(records) == 30, "FUGLE_BINDING_COUNT_INVALID")
    result = {}
    for row in records:
        require(isinstance(row, Mapping), "FUGLE_BINDING_ROW_INVALID")
        symbol = str(row.get("symbol") or "").strip()
        market = str(row.get("market") or "").strip().upper()
        require(symbol and market in {"TWSE", "TPEX"} and symbol not in result, "FUGLE_BINDING_ROW_INVALID")
        result[symbol] = market
    require(Counter(result.values()) == Counter({"TWSE": 25, "TPEX": 5}), "FUGLE_BINDING_MARKET_COUNTS_INVALID")
    return result


def qualify(api_key: str, binding: Mapping[str, Any], *, trading_date: str, cadence: str,
            now_utc: datetime, opener=urlopen, max_age_seconds: int = MAX_AGE_SECONDS) -> dict[str, Any]:
    require(cadence in {"09:30", "12:00"}, "FUGLE_CADENCE_INVALID")
    require(now_utc.tzinfo is not None and now_utc.utcoffset() is not None, "FUGLE_NOW_TIMEZONE_REQUIRED")
    expected = load_binding(binding)
    records = []
    request_count = 0
    for symbol, expected_market in expected.items():
        require(request_count < MAX_REQUESTS, "FUGLE_REQUEST_CAP_EXCEEDED")
        raw = _request(symbol, api_key, opener)
        request_count += 1
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
    require(request_count == 30 and len(records) == 30, "FUGLE_EXACT_30_REQUIRED")
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
        "automatic_retries": 0,
        "fallback_used": False,
        "token_persisted": False,
        "license_gate": "UNPROVEN_REQUIRES_PROVIDER_CONFIRMATION_FOR_NON_DISPLAY_AUTOMATED_USE",
        "production_eligible": False,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "records": records,
    }

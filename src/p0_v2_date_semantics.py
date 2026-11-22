"""P0 V2 *offline-only* source-date and receipt candidate.

No network calls, no official-calendar authority, no Production admission.
Caller-supplied fixture bytes and timestamps are not trusted source evidence.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Any, Mapping

SCHEMA = "RATE-P0-V2-SOURCE-RECEIPT-OFFLINE-CANDIDATE-V1"
ALLOWED_ENDPOINTS = {
    ("TWSE", "classification"): "https://isin.twse.com.tw/isin/e_C_public.jsp?strMode=2",
    ("TPEX", "classification"): "https://isin.twse.com.tw/isin/e_C_public.jsp?strMode=4",
    ("TWSE", "market_daily"): "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
    ("TPEX", "market_daily"): "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
}
MARKETS = ("TWSE", "TPEX")


class V2Blocked(ValueError):
    """Fail-closed rejection with stable reason codes."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise V2Blocked(reason)


def parse_date(value: str, reason: str = "V2_DATE_INVALID") -> date:
    require(isinstance(value, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)), reason)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise V2Blocked(reason) from exc


def parse_utc(value: str) -> datetime:
    require(isinstance(value, str) and bool(re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", value
    )), "V2_OBSERVATION_UTC_REQUIRED")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise V2Blocked("V2_OBSERVATION_UTC_REQUIRED") from exc
    require(parsed.utcoffset() == timedelta(0), "V2_OBSERVATION_UTC_REQUIRED")
    return parsed


def build_source_receipt(*, market: str, dataset_role: str, endpoint: str,
                         trading_date: str, source_update_date_raw: str | None,
                         observed_at_utc: str, body: bytes, http_status: int,
                         final_url: str, content_length: int,
                         fallback_used: bool = False) -> dict[str, Any]:
    """Check an offline fixture envelope, NOT official issuance or historical truth."""
    target = parse_date(trading_date)
    require((market, dataset_role) in ALLOWED_ENDPOINTS
            and endpoint == ALLOWED_ENDPOINTS[(market, dataset_role)],
            "V2_SOURCE_ENDPOINT_NOT_ALLOWLISTED")
    require(http_status == 200 and final_url == endpoint and fallback_used is False,
            "V2_SOURCE_TRANSPORT_UNQUALIFIED")
    require(isinstance(body, bytes) and bool(body) and type(content_length) is int
            and content_length == len(body), "V2_SOURCE_BYTES_INCOMPLETE")
    observed = parse_utc(observed_at_utc)
    observed_taipei_date = observed.astimezone(timezone(timedelta(hours=8))).date()
    updated = None
    if source_update_date_raw is not None:
        require(isinstance(source_update_date_raw, str)
                and bool(re.fullmatch(r"\d{4}/\d{2}/\d{2}", source_update_date_raw)),
                "V2_SOURCE_UPDATE_DATE_INVALID")
        updated = parse_date(source_update_date_raw.replace("/", "-"),
                             "V2_SOURCE_UPDATE_DATE_INVALID")
        require(updated <= observed_taipei_date, "V2_SOURCE_UPDATE_DATE_FUTURE_TO_OBSERVATION")
    require(dataset_role != "classification" or updated is not None,
            "V2_CLASSIFICATION_UPDATE_DATE_MISSING")
    candidate = {
        "schema": SCHEMA, "market": market, "dataset_role": dataset_role,
        "endpoint": endpoint, "trading_date": target.isoformat(),
        "source_update_date_raw": source_update_date_raw,
        "source_update_date_parsed": updated.isoformat() if updated else None,
        "date_relation": ("UNKNOWN" if updated is None else
                          "EQUAL_NOMINAL_DATE" if updated == target else "DIFFERENT_NOMINAL_DATE"),
        "publication_time": None, "effective_from": None,
        "effective_to_exclusive": None, "observed_at_utc": observed_at_utc,
        "response_bytes": len(body), "raw_body_sha256": hashlib.sha256(body).hexdigest(),
        "source_provenance_status": "UNVERIFIED_OFFLINE_FIXTURE",
        "source_valid_for_trading_date": "NOT_ESTABLISHED",
        "date_semantics_authority": "UNQUALIFIED",
        "pit_coverage_status": "UNKNOWN",
        "fallback_used": False, "production_permit": "NOT_ISSUED",
        "production_credit": 0, "cer081_credit": 0,
    }
    candidate["candidate_receipt_sha256"] = hashlib.sha256(
        json.dumps(candidate, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return candidate


def assess_calendar_fixture(trading_date: str, calendars: Mapping[str, Mapping[str, str]]) -> dict[str, Any]:
    """Both exchange calendars must claim OPEN; no official validity is established."""
    parse_date(trading_date)
    require(isinstance(calendars, Mapping) and set(calendars) == set(MARKETS),
            "V2_CALENDAR_COVERAGE_MISSING")
    for market in MARKETS:
        item = calendars[market]
        require(isinstance(item, Mapping) and item.get("trading_date") == trading_date,
                "V2_CALENDAR_DATE_MISMATCH")
        status = item.get("status")
        require(status in ("OPEN", "CLOSED", "UNKNOWN"),
                "V2_CALENDAR_STATUS_INVALID")
        require(status == "OPEN",
                "V2_TRADING_DAY_CLOSED" if status == "CLOSED" else "V2_CALENDAR_UNKNOWN")
        require(bool(re.fullmatch(r"[0-9a-f]{64}", str(item.get("receipt_sha256", "")))),
                "V2_CALENDAR_RECEIPT_MISSING")
    return {"calendar_model": "PASS_OFFLINE_FIXTURE",
            "official_calendar_authority": "UNVERIFIED",
            "production_permit": "NOT_ISSUED"}

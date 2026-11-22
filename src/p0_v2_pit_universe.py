"""P0 V2 offline-only point-in-time eligibility structural model.

A passing synthetic fixture is NOT official full-market coverage. Never grant
historical Production eligibility or CER-081 credit.
"""
from __future__ import annotations

from datetime import timedelta, timezone
import re
from typing import Any, Mapping, Sequence

from src.p0_v2_date_semantics import MARKETS, parse_date, parse_utc, require

SCHEMA = "RATE-P0-V2-PIT-UNIVERSE-OFFLINE-CANDIDATE-V1"
NORMAL_LISTING = {"TWSE": ("TWSE LISTED", "TAIWAN INNOVATION BOARD"),
                  "TPEX": ("TPEx LISTED",)}
LIFECYCLE = ("ACTIVE", "SUSPENDED", "TERMINATED", "TRANSFERRED")
DIGEST = re.compile(r"[0-9a-f]{64}")

# Conservative structural fixture subset, NOT the complete ISO 10962 code list.
# ES = ordinary/common equity; CE = collective investment vehicle / ETF, excluded.
# For candidate admission an unrecognized group or attribute always fails closed.
# Unknown or non-applicable attributes are NOT accepted as proof of ordinary share
# eligibility. Official CFI assignment and historical source authority are still
# independently UNVERIFIED.
CFI_CANDIDATE_ATTRIBUTES = {
    "ES": ("VNRE", "TU", "OPF", "BRNM"),
    "CE": ("COM", "IGJ", "RBEVLCDFKM", "SU"),
}


def _is_common_share_cfi(cfi: object) -> bool:
    """Check exactly six uppercase ASCII codes and known group/attribute domains.

    A structurally recognized fixture does not prove authoritative ISO assignment
    or official classification for a specific listed instrument.
    """
    require(isinstance(cfi, str) and re.fullmatch(r"[A-Z]{6}", cfi) is not None,
            "PIT_CFI_UNKNOWN")
    group = cfi[:2]
    require(group in CFI_CANDIDATE_ATTRIBUTES, "PIT_CFI_GROUP_UNQUALIFIED")
    for value, allowed in zip(cfi[2:], CFI_CANDIDATE_ATTRIBUTES[group]):
        require(value in allowed, "PIT_CFI_ATTRIBUTE_UNQUALIFIED")
    return group == "ES"


def assess_pit_model(*, trading_date: str, rows: Sequence[Mapping[str, Any]],
                     coverage: Mapping[str, Mapping[str, Any]],
                     calendars: Mapping[str, Mapping[str, str]]) -> dict[str, Any]:
    """Validate a synthetic *structural candidate*, never official eligibility.

    Output separates position-domain structure from unverified joint CFI
    semantics, instrument assignment, and blocked historical PIT authority.
    """
    day = parse_date(trading_date)
    from src.p0_v2_date_semantics import assess_calendar_fixture
    assess_calendar_fixture(trading_date, calendars)
    require(isinstance(rows, (list, tuple)) and bool(rows),
            "BLOCKED_PIT_HISTORY_GAP")
    require(isinstance(coverage, Mapping) and set(coverage) == set(MARKETS),
            "BLOCKED_PIT_HISTORY_GAP")
    seen, by_market = set(), {m: set() for m in MARKETS}
    eligible, nontrading = [], []
    for row in rows:
        require(isinstance(row, Mapping), "PIT_RECORD_INVALID")
        market, symbol = row.get("market"), row.get("symbol")
        require(market in MARKETS and isinstance(symbol, str) and bool(symbol.strip()),
                "PIT_RECORD_INVALID")
        require(row.get("listing_market") in NORMAL_LISTING[market],
                "PIT_LISTING_MARKET_MISMATCH")
        require(symbol not in seen, "PIT_CROSS_MARKET_DUPLICATE")
        seen.add(symbol)
        by_market[market].add(symbol)
        cfi = row.get("cfi_code")
        is_common_share = _is_common_share_cfi(cfi)
        require(isinstance(row.get("isin"), str) and bool(row["isin"]),
                "PIT_ISIN_MISSING")
        require(bool(re.fullmatch(r"[0-9a-f]{64}", str(row.get("receipt_sha256", ""))))
                and isinstance(row.get("source_event_id"), str)
                and bool(row["source_event_id"].strip()),
                "BLOCKED_PIT_HISTORY_GAP")
        start = row.get("effective_from")
        require(start is not None, "BLOCKED_PIT_HISTORY_GAP")
        from_day = parse_date(start, "PIT_EFFECTIVE_DATE_INVALID")
        end = row.get("effective_to_exclusive")
        end_day = parse_date(end, "PIT_EFFECTIVE_DATE_INVALID") if end is not None else None
        require(end_day is None or from_day < end_day, "PIT_INTERVAL_INVALID")
        require(from_day <= day and (end_day is None or day < end_day),
                "PIT_EFFECTIVE_INTERVAL_MISMATCH")
        life = row.get("lifecycle")
        require(life in LIFECYCLE, "PIT_LIFECYCLE_UNKNOWN")
        common_and_normal = is_common_share and row.get("listing_market") in NORMAL_LISTING[market]
        expected = common_and_normal and life not in ("TERMINATED", "TRANSFERRED")
        require(row.get("eligible") is expected, "PIT_ELIGIBILITY_CONFLICT")
        if expected:
            eligible.append((market, symbol))
            if life == "SUSPENDED":
                nontrading.append((market, symbol))
    for market in MARKETS:
        item = coverage[market]
        require(isinstance(item, Mapping)
                and item.get("model_history_complete") is True
                and isinstance(item.get("expected_symbols"), list)
                and len(item["expected_symbols"]) == len(set(item["expected_symbols"]))
                and set(item["expected_symbols"]) == by_market[market],
                "BLOCKED_PIT_HISTORY_GAP")
        require(item.get("covered_from") is not None
                and item.get("covered_through") is not None,
                "BLOCKED_PIT_HISTORY_GAP")
        require(parse_date(item["covered_from"]) <= day <= parse_date(item["covered_through"]),
                "BLOCKED_PIT_HISTORY_GAP")
        require(bool(DIGEST.fullmatch(str(item.get("history_receipt_sha256", "")))),
                "BLOCKED_PIT_HISTORY_GAP")
    return {
        "schema": SCHEMA, "trading_date": trading_date,
        "structural_model_status": "PASS_OFFLINE_FIXTURE",
        "qualification_scope": "SYNTHETIC_STRUCTURAL_FIXTURE_ONLY",
        # Only format and allowed position values passed. A six-character
        # combination can be position-valid without proven joint semantics.
        "CFI_FORMAT_VALID": "PASS_LIMITED_OFFLINE_STRUCTURE",
        "CFI_POSITION_DOMAIN_VALID": "PASS_LIMITED_OFFLINE_STRUCTURE",
        "CFI_FULL_COMBINATION_VALID": "UNVERIFIED",
        "CFI_INSTRUMENT_ASSIGNMENT_VALID": "UNVERIFIED",
        "PIT_UNIVERSE_VERIFIED": "BLOCKED",
        "historical_source_authority": "UNVERIFIED",
        "pit_coverage_status": "BLOCKED_PIT_HISTORY_GAP",
        # Never emit eligible_fixture_symbols: the legacy field name could
        # be mistaken for an independently qualified full-market universe.
        "offline_structural_candidate_symbols_only": sorted(eligible),
        "offline_suspended_structural_candidates_only": sorted(nontrading),
        "full_market_coverage_qualified": False, "fallback_used": False,
        "production_permit": "NOT_ISSUED", "production_credit": 0,
        "cer081_credit": 0,
    }


def assess_forward_snapshot(*, snapshot_date: str, observed_at_utc: str,
                            claimed_trading_date: str, sha256: str) -> dict[str, str]:
    """A nominal observation cannot prove earlier or later effective-date truth."""
    parse_date(snapshot_date)
    parse_date(claimed_trading_date)
    observed_day = parse_utc(observed_at_utc).astimezone(
        timezone(timedelta(hours=8))).date().isoformat()
    require(bool(DIGEST.fullmatch(sha256)), "PIT_SNAPSHOT_DIGEST_INVALID")
    require(snapshot_date == observed_day, "PIT_SNAPSHOT_DATE_UNATTESTED")
    require(claimed_trading_date == observed_day, "BLOCKED_PIT_HISTORY_GAP")
    return {"snapshot_status": "OBSERVED_ONLY_OFFLINE",
            "qualification_scope": "SYNTHETIC_OBSERVATION_ONLY",
            "CFI_FORMAT_VALID": "UNVERIFIED",
            "CFI_POSITION_DOMAIN_VALID": "UNVERIFIED",
            "CFI_FULL_COMBINATION_VALID": "UNVERIFIED",
            "CFI_INSTRUMENT_ASSIGNMENT_VALID": "UNVERIFIED",
            "PIT_UNIVERSE_VERIFIED": "BLOCKED",
            "pit_coverage_status": "BLOCKED_PIT_HISTORY_GAP",
            "production_permit": "NOT_ISSUED",
            "production_credit": 0, "cer081_credit": 0}

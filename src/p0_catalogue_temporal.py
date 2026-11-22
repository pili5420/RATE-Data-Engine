"""Source-update date semantics: fail closed until authoritative effective-date proof.

The ISIN page's Date Stock Updated is not necessarily a stock-trading date.
No source-update/trading-date inequality can become Production PASS without a
separately adopted authoritative validity contract and independent evidence.
"""
from __future__ import annotations

from datetime import date


def assess_classification_source_date(*, trading_date: str,
                                      source_update_date: str) -> dict:
    target = date.fromisoformat(trading_date)
    updated = date.fromisoformat(source_update_date)
    comparison = "EQUAL" if updated == target else (
        "SOURCE_BEFORE_TARGET" if updated < target else "SOURCE_AFTER_TARGET")
    return {
        "target_trading_date": target.isoformat(),
        "classification_page_updated_date": updated.isoformat(),
        "classification_date_role": "ISIN_PAGE_DATE_STOCK_UPDATED_NOT_TRADING_DATE",
        "comparison": comparison,
        "admission": "PASS" if comparison == "EQUAL" else "BLOCK",
        "authority_for_non_equal_effective_date": "NOT_ADOPTED",
        "reason": "NONE" if comparison == "EQUAL" else "STALE_OR_FUTURE_CATALOGUE",
    }


def require_classification_admission(*, trading_date: str,
                                      source_update_date: str) -> dict:
    evidence = assess_classification_source_date(
        trading_date=trading_date, source_update_date=source_update_date)
    if evidence["admission"] != "PASS":
        raise RuntimeError("STALE_OR_FUTURE_CATALOGUE")
    return evidence

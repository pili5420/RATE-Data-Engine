"""Independent raw, semantic and knowledge-time evidence; unknowns stay unknown."""
from dataclasses import dataclass, field
from typing import Optional


class Rejected(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise Rejected(reason)


@dataclass(frozen=True)
class Fact:
    symbol: str
    market: str
    issuer_identity: str
    concept: str
    eps_basis: str
    statement_scope: str
    period_start: str
    period_end: str
    duration: str
    raw_value: str
    normalized_value: Optional[str]
    unit: str
    scale: Optional[str]
    decimals: Optional[str]
    precision: Optional[str]
    filing_identity: Optional[str]
    document_identity: str
    revision_identity: Optional[str]
    source_representation: str
    raw_sha256: str
    receipt_reference: str
    context_reference: str
    locator: str
    first_verified_observed_at: str
    source_publication_time: Optional[str] = None
    publication_precision: str = "UNPROVEN"
    publication_evidence: Optional[str] = None
    raw_integrity_status: str = "PASS"
    fact_semantics_status: str = "UNPROVEN"
    historical_pit_status: str = "UNPROVEN"
    pit_selection_status: str = "UNPROVEN"
    knowledge_time_basis: str = "OBSERVED_FORWARD_ONLY"
    issuer_period_group: Optional[str] = None
    production_eligible: bool = field(default=False, init=False)
    original_eight_quarter_coverage_credit: int = field(default=0, init=False)


@dataclass(frozen=True)
class Expectation:
    symbol: str
    market: str
    period_start: str
    period_end: str
    duration: str = "QUARTER"
    eps_basis: str = "BASIC"
    statement_scope: str = "CONSOLIDATED"
    unit: str = "TWD/shares"


@dataclass(frozen=True)
class FiscalCalendar:
    symbol: str
    start_month: int
    body_sha256: str
    receipt_reference: str
    locator: str


def validate_semantics(fact, expected):
    require(fact.raw_integrity_status == "PASS", "RAW_INTEGRITY_UNPROVEN")
    require(fact.symbol == expected.symbol and fact.issuer_identity == expected.symbol,
            "WRONG_ISSUER")
    require(fact.market == expected.market, "WRONG_MARKET")
    require(fact.eps_basis == expected.eps_basis, "BASIC_DILUTED_MISMATCH")
    local = {"BASIC": "BasicEarningsLossPerShare", "DILUTED": "DilutedEarningsLossPerShare"}.get(expected.eps_basis)
    require(local is not None and fact.concept in (
        "{http://xbrl.ifrs.org/taxonomy/2017-03-09/ifrs-full}" + local,
        "{https://xbrl.ifrs.org/taxonomy/2025-03-27/ifrs-full}" + local), "WRONG_CONCEPT")
    require(fact.statement_scope == expected.statement_scope, "WRONG_SCOPE")
    require(fact.unit == expected.unit, "WRONG_UNIT")
    require(fact.fact_semantics_status == "PASS", "CONCEPT_OR_NUMERIC_UNPROVEN")
    require(fact.duration == expected.duration, "DURATION_MISMATCH")
    require((fact.period_start, fact.period_end) ==
            (expected.period_start, expected.period_end), "WRONG_CONTEXT")
    require(fact.normalized_value is not None, "NUMERIC_UNPROVEN")
    return "PASS"

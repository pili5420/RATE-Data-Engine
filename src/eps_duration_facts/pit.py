"""Candidate knowledge-time gates; no observed timestamp becomes publication time.

Index completeness and exact-public-version attestations are explicit input evidence,
not inferred from a successful fetch. No current source adapter creates them.
"""
from dataclasses import dataclass
from datetime import datetime

from .model import require, validate_semantics


@dataclass(frozen=True)
class Version:
    version_id: str
    symbol: str
    market: str
    period: str
    body_sha256: str
    public_at: str
    publication_precision: str
    publication_evidence: str
    exact_public_version_status: str
    statement_scope: str = "CONSOLIDATED"
    supersedes: str = ""


@dataclass(frozen=True)
class Index:
    symbol: str
    market: str
    window: tuple
    assessed_through: str
    required_pages: tuple
    verified_pages: tuple
    page_receipt_hashes: tuple
    versions: tuple
    completeness_status: str = "UNPROVEN"
    completeness_evidence: str = ""
    version_history_status: str = "UNPROVEN"


def clock(value):
    parsed = datetime.fromisoformat(value)
    require(parsed.tzinfo is not None, "TIMEZONE_UNPROVEN")
    return parsed


def validate_index(index, cutoff):
    require(index.completeness_status == "PASS" and index.completeness_evidence
            and index.version_history_status == "PASS", "INDEX_INCOMPLETE_ANCHOR_UNPROVEN")
    require(index.required_pages and index.required_pages == index.verified_pages
            and len(index.page_receipt_hashes) == len(index.required_pages), "INDEX_PAGINATION_INCOMPLETE")
    require(all(len(h) == 64 and all(c in "0123456789abcdef" for c in h)
                for h in index.page_receipt_hashes), "INDEX_RECEIPT_UNPROVEN")
    require(all(page not in index.required_pages[:n] for n, page in enumerate(index.required_pages)),
            "INDEX_PAGE_DUPLICATE")
    require(clock(index.assessed_through) >= clock(cutoff), "INDEX_CUTOFF_NOT_COVERED")
    ids = []
    for version in index.versions:
        require(version.version_id and version.version_id not in ids, "VERSION_ID_DUPLICATE")
        ids.append(version.version_id)
        require(version.symbol == index.symbol and version.market == index.market, "INDEX_WRONG_ISSUER")
        require(version.period in index.window, "INDEX_PERIOD_OUTSIDE_WINDOW")
        require(version.publication_precision == "SECOND" and version.publication_evidence
                and version.exact_public_version_status == "PASS", "ASOF_VERSION_UNPROVEN")
        clock(version.public_at)
        require(len(version.body_sha256) == 64 and all(c in "0123456789abcdef" for c in version.body_sha256),
                "VERSION_HASH_UNPROVEN")
    for version in index.versions:
        if version.supersedes:
            predecessors = [v for v in index.versions if v.version_id == version.supersedes]
            require(len(predecessors) == 1, "ORIGINAL_VERSION_MISSING")
            previous = predecessors[0]
            require(previous.period == version.period and previous.statement_scope == version.statement_scope
                    and clock(previous.public_at) < clock(version.public_at), "REVISION_LINEAGE_INVALID")
    return "PASS"


def select_version(index, period, cutoff):
    validate_index(index, cutoff)
    candidates = [v for v in index.versions if v.period == period and clock(v.public_at) <= clock(cutoff)]
    require(candidates, "ASOF_VERSION_UNPROVEN")
    latest_time = max(clock(v.public_at) for v in candidates)
    selected = [v for v in candidates if clock(v.public_at) == latest_time]
    require(len(selected) == 1, "VERSION_SELECTION_AMBIGUOUS")
    return selected[0]


def validate_pit(fact, expected, index, period, cutoff):
    validate_semantics(fact, expected)
    require(index.symbol == fact.symbol and index.market == fact.market, "INDEX_WRONG_ISSUER")
    end = datetime.fromisoformat(fact.period_end)
    require(period == str(end.year) + "Q" + str((end.month + 2) // 3), "FACT_PERIOD_BINDING_INVALID")
    version = select_version(index, period, cutoff)
    require(version.statement_scope == fact.statement_scope, "VERSION_SCOPE_MISMATCH")
    require(version.body_sha256 == fact.raw_sha256, "REVISION_LOOKAHEAD_OR_VERSION_HASH_MISMATCH")
    return {"raw_integrity": "PASS", "fact_semantics": "PASS", "historical_pit_status": "PASS",
            "pit_selection_status": "PASS", "selected_version": version.version_id,
            "latest_at_cutoff": True, "production_eligible": False, "coverage_credit": 0}


def observed_forward_only(fact, cutoff):
    require(fact.raw_integrity_status == "PASS", "RAW_INTEGRITY_UNPROVEN")
    require(clock(cutoff) >= clock(fact.first_verified_observed_at), "OBSERVED_ONLY_HISTORICAL_BACKFILL_FORBIDDEN")
    return {"knowledge_time_basis": "OBSERVED_FORWARD_ONLY", "historical_pit_status": "UNPROVEN",
            "production_eligible": False, "coverage_credit": 0}


def select_eight(index, cutoff):
    """Anchor comes from a complete filing index, never successful EPS parsing."""
    validate_index(index, cutoff)
    require(len(index.window) == 10, "BOUNDED_WINDOW_INVALID")
    # Verify the supplied window is consecutive and descending, not a skip policy.
    serials = []
    for period in index.window:
        year, quarter = period.split("Q")
        require(quarter in ("1", "2", "3", "4"), "WINDOW_PERIOD_INVALID")
        serials.append(int(year) * 4 + int(quarter))
    require(all(a - b == 1 for a, b in zip(serials, serials[1:])), "WINDOW_NOT_CONSECUTIVE")
    available = [v.period for v in index.versions if clock(v.public_at) <= clock(cutoff)]
    require(available, "ANCHOR_UNPROVEN")
    position = min(index.window.index(period) for period in available)
    selected = index.window[position:position + 8]
    require(len(selected) == 8, "HISTORY_COVERAGE_INSUFFICIENT")
    require(all(period in available for period in selected), "REQUIRED_QUARTER_MISSING_NO_SUBSTITUTION")
    return selected[0], selected

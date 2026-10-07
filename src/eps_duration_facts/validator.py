"""Composite validation replays semantic material before trusting a serialized fact."""
from dataclasses import asdict

from .model import require
from .parser import parse_inline
from .pit import validate_pit


def validate_fact_replay(fact, receipt, raw_bytes, calendar_evidence=None):
    candidates = parse_inline(receipt, raw_bytes, fact.symbol, fact.market, calendar_evidence)
    matches = [candidate for candidate in candidates if candidate.locator == fact.locator]
    require(len(matches) == 1, "FACT_LOCATOR_INVALID")
    require(asdict(matches[0]) == asdict(fact), "FACT_MATERIAL_TAMPERED")
    return "PASS"


def evaluate(fact, expected, receipt, raw_bytes, calendar_evidence, index, period, cutoff):
    validate_fact_replay(fact, receipt, raw_bytes, calendar_evidence)
    return validate_pit(fact, expected, index, period, cutoff)

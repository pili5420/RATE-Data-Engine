"""Strict V1 control JSON: preserve writer int/float types, never coerce EPS."""
import json
import math
from pathlib import Path

from .eps_duration_facts.model import require
from .eps_duration_facts.raw import sha256
from .provider_eps_candidate import _canonical, _time
from .provider_eps_dispatch import PROTOCOL

VERSION = "RATE_PROVIDER_CONTROL_JSON_V1"


def _object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "METADATA_DUPLICATE_KEY")
        result[key] = value
    return result


def _constant(value):
    require(False, "METADATA_NONFINITE_NUMBER:" + value)


def _finite(value):
    if isinstance(value, float):
        require(math.isfinite(value), "METADATA_NONFINITE_NUMBER")
    elif isinstance(value, dict):
        for item in value.values():
            _finite(item)
    elif isinstance(value, list):
        for item in value:
            _finite(item)


def read_metadata(body):
    value = json.loads(body, object_pairs_hook=_object, parse_constant=_constant)
    _finite(value)
    require(isinstance(value, dict), "METADATA_OBJECT_REQUIRED")
    return value


def number(value, *, minimum=0):
    require(type(value) in (int, float) and minimum <= value <= float.fromhex("0x1.fffffffffffffp+1023") and math.isfinite(value),
            "DISPATCH_NUMBER_INVALID")
    return value


def read_intent(path, plan):
    path = Path(path)
    intent = read_metadata(path.read_bytes())
    symbol = intent.get("symbol")
    markets = {s["symbol"]: s["market"] for s in plan["universe"]["stocks"]}
    require(intent.get("plan_id") == plan["plan_id"] and symbol in markets and path.stem == symbol,
            "REQUEST_INTENT_PLAN_MISMATCH")
    query = {**plan["query"], "data_id": symbol}
    if "query" in intent:
        require(intent["query"] == query, "REQUEST_INTENT_QUERY_MISMATCH")
    if "market" in intent:
        require(intent["market"] == markets[symbol], "REQUEST_INTENT_MARKET_MISMATCH")
    # Pre-dispatch legacy intents still fail closed on unknown request outcome.
    if "dispatch_evidence" not in intent:
        require("dispatch_evidence_sha256" not in intent, "DISPATCH_EVIDENCE_MISSING")
        return intent
    evidence = intent["dispatch_evidence"]
    require(intent.get("query") == query and intent.get("market") == markets[symbol],
            "DISPATCH_INTENT_BINDING_INVALID")
    _time(intent.get("started_at"))
    require(isinstance(evidence, dict) and intent.get("dispatch_evidence_sha256") ==
            sha256(_canonical(evidence)), "DISPATCH_EVIDENCE_TAMPERED")
    require(evidence.get("request_identity") == {"plan_id": plan["plan_id"], "symbol": symbol,
            "request_id": "coverage-" + symbol, "query": query}, "DISPATCH_REQUEST_BINDING_INVALID")
    fields = {"protocol", "request_identity", "session_identity", "clock_domain", "monotonic_timestamp",
        "utc_timestamp", "previous_dispatch_interval_seconds", "actual_wait_seconds", "minimum_interval_seconds",
        "previous_wait_anchor_monotonic", "prior_session_continuity", "measurement_boundary"}
    require(set(evidence) == fields and evidence["protocol"] == PROTOCOL and
            evidence["measurement_boundary"] == "CAPTURE_CALL_NOT_HTTP_WIRE_START", "DISPATCH_SCHEMA_INVALID")
    session = evidence["session_identity"]
    require(isinstance(session, str) and bool(session) and
            evidence["clock_domain"] == "PROCESS_SESSION:" + session, "DISPATCH_SESSION_BINDING_INVALID")
    _time(evidence["utc_timestamp"])
    timestamp = number(evidence["monotonic_timestamp"])
    interval = number(evidence["minimum_interval_seconds"], minimum=13)
    number(evidence["actual_wait_seconds"])
    gap, anchor = evidence["previous_dispatch_interval_seconds"], evidence["previous_wait_anchor_monotonic"]
    continuity = evidence["prior_session_continuity"]
    require(continuity in {"NO_PRIOR_DISPATCH", "UNPROVEN_CONSERVATIVE_WAIT", "SAME_MONOTONIC_DOMAIN"},
            "DISPATCH_CONTINUITY_INVALID")
    if anchor is not None:
        require(timestamp - number(anchor) >= interval, "DISPATCH_INTERVAL_VIOLATION")
    if continuity == "NO_PRIOR_DISPATCH":
        require(gap is None and anchor is None, "DISPATCH_CONTINUITY_INVALID")
    elif continuity == "UNPROVEN_CONSERVATIVE_WAIT":
        require(gap is None and anchor is not None and evidence["actual_wait_seconds"] >= interval,
                "DISPATCH_CONTINUITY_INVALID")
    else:
        require(anchor is not None and number(gap, minimum=interval) <= timestamp,
                "DISPATCH_CONTINUITY_INVALID")
    return intent


def validate_dispatches(root, plan):
    """Shared restart/controller audit; never compare distinct clock domains."""
    intents = [read_intent(p, plan) for p in sorted((Path(root) / "intents").glob("*.json"))]
    groups = {}
    for intent in intents:
        if "dispatch_evidence" in intent:
            evidence = intent["dispatch_evidence"]
            groups.setdefault(evidence["session_identity"], []).append(evidence)
    for records in groups.values():
        records.sort(key=lambda r: r["monotonic_timestamp"])
        require(records[0]["previous_dispatch_interval_seconds"] is None, "DISPATCH_FIRST_GAP_INVALID")
        for prior, current in zip(records, records[1:]):
            gap = current["monotonic_timestamp"] - prior["monotonic_timestamp"]
            require(current["prior_session_continuity"] == "SAME_MONOTONIC_DOMAIN" and
                    gap >= current["minimum_interval_seconds"] and
                    math.isclose(gap, current["previous_dispatch_interval_seconds"], rel_tol=0, abs_tol=1e-6),
                    "DISPATCH_SESSION_INTERVAL_INVALID")
    return intents

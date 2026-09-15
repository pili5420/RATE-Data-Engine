from __future__ import annotations
from datetime import datetime
from typing import Mapping, Sequence

ALLOWED = {"ACTIVE", "SUSPENDED", "RESUMED", "RESTRICTED"}

def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

def map_trading_status(symbol: str, as_of_timestamp: str, symbol_master_valid: bool,
                       events: Sequence[Mapping[str, object]]) -> dict:
    """Map official suspension/restriction events without inferring from company master."""
    if not symbol_master_valid:
        raise ValueError("MISSING_REQUIRED_DATA:invalid_symbol_master")
    as_of = _time(as_of_timestamp)
    applicable = []
    for event in events:
        if event.get("symbol") != symbol:
            continue
        for field in ("source", "effective_start", "source_timestamp", "retrieval_timestamp", "reason", "status"):
            if event.get(field) in (None, ""):
                raise ValueError(f"MISSING_REQUIRED_DATA:trading_status:{field}")
        status = str(event["status"])
        if status not in {"SUSPENDED", "RESUMED", "RESTRICTED"}:
            raise ValueError("TYPE_VALIDATION:trading_status")
        start = _time(str(event["effective_start"]))
        end = _time(str(event["effective_end"])) if event.get("effective_end") else None
        if start <= as_of and (end is None or as_of <= end):
            applicable.append((start, event))
    if not applicable:
        return {"symbol":symbol, "trading_status":"ACTIVE", "lineage":None}
    _, event = sorted(applicable, key=lambda pair: pair[0], reverse=True)[0]
    mapped = "RESTRICTED" if event["status"] == "RESTRICTED" else str(event["status"])
    return {"symbol":symbol, "trading_status":mapped,
            "effective_start":event["effective_start"], "effective_end":event.get("effective_end"),
            "source":event["source"], "source_timestamp":event["source_timestamp"],
            "retrieval_timestamp":event["retrieval_timestamp"], "reason":event["reason"],
            "lineage":{"source":event["source"], "effective_start":event["effective_start"],
                       "effective_end":event.get("effective_end"), "source_timestamp":event["source_timestamp"]}}

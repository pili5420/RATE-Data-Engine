"""FinMind Sponsor Snapshot diagnostic adapter for RATE.

DIAGNOSTIC_ONLY. No Production registry mutation, no scheduler integration, no raw persistence.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

STOCK_URL = "https://api.finmindtrade.com/api/v4/taiwan_stock_tick_snapshot"
FUTURES_URL = "https://api.finmindtrade.com/api/v4/taiwan_futures_snapshot"
TAIPEI = timezone(timedelta(hours=8))
STOCK_REQUIRED = (
    "stock_id", "date", "open", "high", "low", "close",
    "total_volume", "total_amount",
)
FUTURES_REQUIRED = (
    "futures_id", "date", "open", "high", "low", "close", "total_volume",
)
INDEX_IDS = ("001", "101")
SMOKE_STOCK_IDS = ("2330", "2317")


class QualificationError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _finite_number(value):
    if isinstance(value, bool) or value is None:
        raise QualificationError("FINMIND_NUMERIC_INVALID")
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError, OverflowError) as exc:
        raise QualificationError("FINMIND_NUMERIC_INVALID") from exc
    if not math.isfinite(number):
        raise QualificationError("FINMIND_NUMERIC_INVALID")
    return number


def _parse_timestamp(value):
    if not isinstance(value, str) or not value.strip():
        raise QualificationError("FINMIND_TIMESTAMP_MISSING")
    text = value.strip().replace(" ", "T")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise QualificationError("FINMIND_TIMESTAMP_INVALID") from exc
    assumed = dt.tzinfo is None
    if assumed:
        dt = dt.replace(tzinfo=TAIPEI)
    return dt.astimezone(timezone.utc), assumed


def _request(url, token, params, opener=urlopen, *, now=_now):
    if not token:
        raise QualificationError("FINMIND_TOKEN_NOT_INJECTED")
    query = urlencode(params, doseq=True)
    req = Request(
        url + ("?" + query if query else ""),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with opener(req, timeout=30) as response:
            body = response.read()
            status = getattr(response, "status", response.getcode())
            content_type = response.headers.get("Content-Type", "")
            final_url = response.geturl()
    except HTTPError as exc:
        if exc.code == 401:
            raise QualificationError("FINMIND_INVALID_TOKEN") from exc
        if exc.code == 403:
            raise QualificationError("FINMIND_PLAN_NOT_AUTHORIZED") from exc
        if exc.code == 429:
            raise QualificationError("FINMIND_RATE_LIMIT") from exc
        raise QualificationError(f"FINMIND_HTTP_{exc.code}") from exc
    except (URLError, TimeoutError, ConnectionError) as exc:
        raise QualificationError("FINMIND_CONNECTIVITY_FAILURE") from exc
    if status != 200:
        raise QualificationError(f"FINMIND_HTTP_{status}")
    if not body:
        raise QualificationError("FINMIND_EMPTY_RESPONSE")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError("FINMIND_NON_JSON_RESPONSE") from exc
    if not isinstance(payload, dict):
        raise QualificationError("FINMIND_RESPONSE_CONTAINER_INVALID")
    provider_status = payload.get("status")
    if provider_status not in (200, "200"):
        raise QualificationError("FINMIND_PROVIDER_STATUS_NOT_200:" + str(provider_status))
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise QualificationError("FINMIND_DATA_NOT_LIST")
    receipt = {
        "endpoint": url,
        "query": params,
        "http_status": status,
        "content_type": content_type,
        "final_url": final_url.split("?")[0],
        "response_bytes": len(body),
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "retrieved_at": now(),
    }
    return rows, receipt


def fetch_stock_all(token, opener=urlopen, *, now=_now):
    return _request(STOCK_URL, token, {"data_id": ""}, opener, now=now)


def fetch_indices(token, opener=urlopen, *, now=_now):
    return _request(STOCK_URL, token, {"data_id": list(INDEX_IDS)}, opener, now=now)


def fetch_txf(token, opener=urlopen, *, now=_now):
    return _request(FUTURES_URL, token, {"data_id": "TXF"}, opener, now=now)


def normalize_stock_rows(rows):
    out, seen = [], set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise QualificationError("FINMIND_STOCK_ROW_NOT_OBJECT")
        missing = [k for k in STOCK_REQUIRED if k not in row]
        if missing:
            raise QualificationError("FINMIND_STOCK_SCHEMA_MISSING:" + ",".join(missing))
        symbol = str(row["stock_id"]).strip()
        if not symbol or symbol in seen:
            raise QualificationError("FINMIND_STOCK_DUPLICATE_OR_EMPTY_ID:" + symbol)
        seen.add(symbol)
        stamp, assumed = _parse_timestamp(row["date"])
        numeric = {}
        for key in ("open", "high", "low", "close", "total_volume", "total_amount"):
            numeric[key] = _finite_number(row[key])
        out.append({
            "id": symbol,
            "timestamp_utc": stamp.isoformat(),
            "timestamp_timezone_assumed_asia_taipei": assumed,
            "numeric": numeric,
            "row_index": index,
        })
    return out


def normalize_futures_rows(rows):
    out, seen = [], set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise QualificationError("FINMIND_FUTURES_ROW_NOT_OBJECT")
        missing = [k for k in FUTURES_REQUIRED if k not in row]
        if missing:
            raise QualificationError("FINMIND_FUTURES_SCHEMA_MISSING:" + ",".join(missing))
        fid = str(row["futures_id"]).strip()
        if not fid or fid in seen:
            raise QualificationError("FINMIND_FUTURES_DUPLICATE_OR_EMPTY_ID:" + fid)
        seen.add(fid)
        stamp, assumed = _parse_timestamp(row["date"])
        numeric = {}
        for key in ("open", "high", "low", "close", "total_volume"):
            numeric[key] = _finite_number(row[key])
        out.append({
            "id": fid,
            "timestamp_utc": stamp.isoformat(),
            "timestamp_timezone_assumed_asia_taipei": assumed,
            "numeric": numeric,
            "row_index": index,
        })
    return out


def load_universe(path):
    if not path:
        return None
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    values = obj.get("stocks") if isinstance(obj, dict) and isinstance(obj.get("stocks"), list) else obj
    if not isinstance(values, list):
        raise QualificationError("FINMIND_UNIVERSE_FORMAT_INVALID")
    symbols, markets = [], {}
    for item in values:
        if isinstance(item, dict):
            symbol = str(item.get("symbol") or item.get("stock_id") or "").strip()
            market = item.get("market")
        else:
            symbol, market = str(item).strip(), None
        if not symbol or symbol in markets:
            raise QualificationError("FINMIND_UNIVERSE_DUPLICATE_OR_EMPTY")
        symbols.append(symbol)
        markets[symbol] = market
    return {"symbols": symbols, "markets": markets}


def _freshness(rows, now_utc, ids, max_age_seconds):
    mapped = {r["id"]: r for r in rows}
    evidence = {}
    ok = True
    for ident in ids:
        row = mapped.get(ident)
        if row is None:
            evidence[ident] = {"status": "MISSING"}
            ok = False
            continue
        age = (now_utc - datetime.fromisoformat(row["timestamp_utc"])).total_seconds()
        evidence[ident] = {
            "status": "PASS" if 0 <= age <= max_age_seconds else "STALE_OR_FUTURE",
            "age_seconds": age,
            "timezone_assumed_asia_taipei": row["timestamp_timezone_assumed_asia_taipei"],
        }
        if not 0 <= age <= max_age_seconds:
            ok = False
    return ok, evidence


def qualify(token, *, universe_path=None, opener=urlopen, now=None, max_stock_age_seconds=120, max_futures_age_seconds=180):
    current = now or datetime.now(timezone.utc)
    calls = []

    stock_raw, stock_receipt = fetch_stock_all(token, opener, now=lambda: current.isoformat())
    calls.append(stock_receipt)
    index_raw, index_receipt = fetch_indices(token, opener, now=lambda: current.isoformat())
    calls.append(index_receipt)
    futures_raw, futures_receipt = fetch_txf(token, opener, now=lambda: current.isoformat())
    calls.append(futures_receipt)

    stock = normalize_stock_rows(stock_raw)
    indices = normalize_stock_rows(index_raw)
    futures = normalize_futures_rows(futures_raw)

    stock_ids = {r["id"] for r in stock}
    index_ids = {r["id"] for r in indices}
    futures_ids = {r["id"] for r in futures}

    index_gate = set(INDEX_IDS).issubset(index_ids)
    futures_gate = bool(futures_ids) and all(fid.startswith("TXF") for fid in futures_ids)

    stock_fresh, stock_freshness = _freshness(stock + indices, current, INDEX_IDS + SMOKE_STOCK_IDS, max_stock_age_seconds)
    futures_probe_ids = tuple(sorted(futures_ids)[:3])
    futures_fresh, futures_freshness = _freshness(futures, current, futures_probe_ids, max_futures_age_seconds) if futures_probe_ids else (False, {})

    universe = load_universe(universe_path)
    if universe is None:
        coverage = {
            "status": "INCONCLUSIVE_FULL_UNIVERSE_INPUT_REQUIRED",
            "expected_count": None,
            "covered_count": None,
            "coverage_ratio": None,
            "missing_count": None,
            "missing_sample": [],
        }
        coverage_gate = False
    else:
        expected = set(universe["symbols"])
        missing = sorted(expected - stock_ids)
        covered = len(expected & stock_ids)
        coverage = {
            "status": "PASS" if not missing else "FAIL_CLOSED",
            "expected_count": len(expected),
            "covered_count": covered,
            "coverage_ratio": covered / len(expected) if expected else 0.0,
            "missing_count": len(missing),
            "missing_sample": missing[:20],
        }
        coverage_gate = not missing and len(expected) == 1978\n        if len(expected) != 1978:\n            coverage["status"] = "FAIL_CLOSED:EXPECTED_1978_UNIVERSE"

    timestamp_assumption_present = any(r["timestamp_timezone_assumed_asia_taipei"] for r in stock + indices + futures)

    hard_gates = {
        "request_count_exactly_3": len(calls) == 3,
        "stock_endpoint_access": bool(stock),
        "index_001_101_present": index_gate,
        "txf_family_present": futures_gate,
        "stock_freshness_candidate": stock_fresh,
        "futures_freshness_candidate": futures_fresh,
        "full_universe_coverage": coverage_gate,
    }

    if all(hard_gates.values()) and not timestamp_assumption_present:
        classification = "PASS_CANDIDATE"
    elif all(v for k, v in hard_gates.items() if k != "full_universe_coverage") and (coverage_gate or universe is None):
        classification = "PARTIAL_CANDIDATE"
    else:
        classification = "FAIL_CLOSED"

    return {
        "artifact_kind": "RATE_FINMIND_INTRADAY_QUALIFICATION_RESULT_V1",
        "scope": "FINMIND_INTRADAY_DIAGNOSTIC_ONLY",
        "provider": "FinMind",
        "classification": classification,
        "requests": calls,
        "request_count": len(calls),
        "stock_snapshot": {
            "row_count": len(stock),
            "unique_id_count": len(stock_ids),
            "four_digit_id_count": sum(len(x) == 4 and x.isdigit() for x in stock_ids),
        },
        "indices": {
            "returned_ids": sorted(index_ids),
            "required_ids": list(INDEX_IDS),
            "freshness": stock_freshness,
        },
        "futures": {
            "returned_ids": sorted(futures_ids),
            "txf_family_count": len(futures_ids),
            "freshness": futures_freshness,
            "near_month_selection_status": "UNPROVEN_BY_SNAPSHOT_SCHEMA",
        },
        "coverage": coverage,
        "timestamp_semantics": {
            "provider_timezone_explicit_in_payload": not timestamp_assumption_present,
            "naive_timestamp_interpretation_if_present": "ASIA_TAIPEI_DIAGNOSTIC_ONLY",
            "production_timestamp_contract_satisfied": False,
        },
        "gates": hard_gates,
        "raw_response_persisted": False,
        "credential_persisted": False,
        "automatic_retries": 0,
        "source_registry_modified": False,
        "production_scheduler_modified": False,
        "external_dependency_resolved": False,
        "decision_eligible": False,
        "production_eligible": False,
    }

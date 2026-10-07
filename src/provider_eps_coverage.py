"""Fixed-universe provider coverage ledger; reuses the candidate EPS validator."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time

from .eps_duration_facts.model import Rejected, require
from .eps_duration_facts.raw import sha256
from .provider_eps_candidate import (API, POLICY, WINDOW, DESCENDING, _canonical,
    _decimal, _json, _policy, _quarter, _time, build_candidate, read_provider_response)

KIND = "PROVIDER_COVERAGE_VALIDATION_ONLY"
COUNTS = {"TWSE": 1085, "TPEX": 893}
QUERY = {"dataset": POLICY["dataset"], "start_date": "2024-07-01", "end_date": "2026-06-30"}
SHARED_STATUSES = {401, 402, 403, 408, 429, 500, 502, 503, 504}


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=True, indent=2, allow_nan=False)
        stream.write("\n")


def load_universe(path, expected_sha256, expected_commit, *, expected_counts=COUNTS):
    """Read historical evidence only; never build/resume the historical plan."""
    from .full_market_catalogue import validate_catalogue
    from .full_market_history import digest, validate_authority
    path = Path(path).resolve()
    body = path.read_bytes()
    require(sha256(body) == expected_sha256, "UNIVERSE_EVIDENCE_HASH_MISMATCH")
    historical = json.loads(body)
    require(historical.get("artifact") == "RATE_FULL_MARKET_HISTORY_PLAN", "UNIVERSE_PLAN_REQUIRED")
    require(historical["plan_id"] == "rate-history-plan-" + digest({k: v for k, v in historical.items() if k != "plan_id"})[:24], "UNIVERSE_PLAN_HASH_MISMATCH")
    validate_authority(historical["runtime_authority"])
    require(historical["runtime_authority"]["commit_sha"] == expected_commit, "UNIVERSE_COMMIT_MISMATCH")
    catalogue = historical["catalogue"]
    validate_catalogue(catalogue, historical["as_of"])
    require(historical["catalogue_sha256"] == digest(catalogue), "UNIVERSE_CATALOGUE_HASH_MISMATCH")
    stocks = [{"symbol": r["symbol"], "market": m["market"]} for m in catalogue["markets"] for r in m["records"] if r["eligible"]]
    require(len({r["symbol"] for r in stocks}) == len(stocks), "UNIVERSE_DUPLICATE_SYMBOL")
    require(dict(Counter(r["market"] for r in stocks)) == expected_counts, "UNIVERSE_COUNTS_MISMATCH")
    shards = [(s["market"], symbol) for s in historical["shards"] for symbol in s["symbols"]]
    require(len(shards) == len(stocks) and set(shards) == {(r["market"], r["symbol"]) for r in stocks}, "UNIVERSE_SHARD_LIST_MISMATCH")
    return {"stocks": sorted(stocks, key=lambda r: (r["market"] != "TWSE", r["symbol"])),
        "verification_status": "PASS", "as_of": catalogue["as_of"], "expected_market_counts": expected_counts,
        "source_path": str(path), "source_file_sha256": expected_sha256, "source_commit": expected_commit,
        "source_plan_id": historical["plan_id"], "catalogue_id": catalogue["catalogue_id"],
        "catalogue_content_hash": catalogue["content_hash"], "catalogue_sha256": historical["catalogue_sha256"],
        "catalogue_json_locator": "$.catalogue", "source_run_id": historical["runtime_authority"]["run_id"]}


def make_plan(universe, code_binding, transport_binding):
    require(universe.get("verification_status") == "PASS", "UNIVERSE_NOT_VERIFIED")
    stocks = universe["stocks"]
    require(stocks and len({r["symbol"] for r in stocks}) == len(stocks), "UNIVERSE_DUPLICATE_SYMBOL")
    require(dict(Counter(r["market"] for r in stocks)) == universe["expected_market_counts"], "UNIVERSE_COUNTS_MISMATCH")
    require(all(r["market"] in COUNTS and re.fullmatch(r"[A-Za-z0-9]+", r["symbol"]) for r in stocks), "UNIVERSE_IDENTITY_INVALID")
    value = {"schema_version": "RATE_PROVIDER_EPS_COVERAGE_PLAN_V1", "artifact_kind": KIND,
        "universe": universe, "source_policy": POLICY, "window": list(WINDOW), "query": QUERY,
        "window_role": "PROVIDER_COVERAGE_WINDOW", "historical_cutoff": "2026-10-05",
        "code_binding": code_binding, "transport_binding": transport_binding, "production_eligible": False,
        "original_eight_quarter_coverage_credit": 0, "formal_eight_quarter_acceptance": "NOT_PERFORMED"}
    value["plan_id"] = "rate-provider-eps-coverage-" + sha256(_canonical(value))
    return value


def validate_plan(plan):
    expected = make_plan(plan["universe"], plan["code_binding"], plan["transport_binding"])
    require(plan == expected, "COVERAGE_PLAN_BINDING_MISMATCH")
    return {r["symbol"]: r["market"] for r in plan["universe"]["stocks"]}


def initialize(root, plan):
    root = Path(root).resolve()
    validate_plan(plan)
    if root.exists():
        require(_json((root / "plan.json").read_bytes()) == plan, "DIFFERENT_COVERAGE_PLAN_FORBIDDEN")
    else:
        root.mkdir(parents=True, exist_ok=False)
        save(root / "plan.json", plan)
        for name in ("events", "intents", "raw", "receipts", "reports"):
            (root / name).mkdir()
    return root


def result_entry(plan, symbol, rows=(), issues=(), *, status=None, reason=None, origin="NEW_PROVIDER_REQUEST", references=(), integrity=None, shared_stop=False):
    markets = validate_plan(plan)
    require(symbol in markets, "SYMBOL_NOT_IN_PLAN")
    rows = list(rows)
    require(len({r["analysis_quarter"] for r in rows}) == len(rows), "LEDGER_DUPLICATE_QUARTER")
    require(all(r["symbol"] == symbol and r["analysis_quarter"] in WINDOW for r in rows), "LEDGER_ROW_IDENTITY_MISMATCH")
    rows.sort(key=lambda r: WINDOW.index(r["analysis_quarter"]), reverse=True)
    rows = [{**r, "market": markets[symbol], "coverage_plan_id": plan["plan_id"]} for r in rows]
    if status is None:
        status = ("VALIDATION_FAILED" if any(i.get("target_position") for i in issues) else
                  "COMPLETE" if len(rows) == 8 else "HISTORICAL_INSUFFICIENT" if rows else "NO_EPS")
    return {"plan_id": plan["plan_id"], "symbol": symbol, "market": markets[symbol], "status": status,
        "reason": reason, "origin": origin, "quarter_order": "LATEST_TO_OLDEST", "rows": rows,
        "issues": list(issues), "receipt_references": list(references), "input_integrity": integrity or {},
        "shared_host_stop": shared_stop, "recorded_at": now(), "production_eligible": False,
        "original_eight_quarter_coverage_credit": 0}


def append_event(root, entry):
    root = Path(root)
    require(entry["plan_id"] == _json((root / "plan.json").read_bytes())["plan_id"], "LEDGER_PLAN_MISMATCH")
    entry = {**entry, "event_sha256": sha256(_canonical(entry))}
    save(root / "events" / (entry["symbol"] + ".json"), entry)
    return entry


def read_events(root, plan):
    markets = validate_plan(plan)
    events = {}
    core = ("symbol", "provider_date", "analysis_quarter", "provider_value", "raw_sha256", "receipt_sha256",
            "json_locator", "raw_row_index_zero_based", "acquired_observed_at", "raw_bytes")
    for path in sorted((Path(root) / "events").glob("*.json")):
        entry = _json(path.read_bytes())
        require(entry.get("event_sha256") == sha256(_canonical({k: v for k, v in entry.items() if k != "event_sha256"})), "LEDGER_TAMPERED")
        symbol = entry["symbol"]
        require(entry["plan_id"] == plan["plan_id"] and markets.get(symbol) == entry["market"] and path.stem == symbol and symbol not in events, "LEDGER_PLAN_OR_MARKET_MISMATCH")
        for filename, expected in entry["input_integrity"].items():
            body = Path(filename).read_bytes()
            require(len(body) == expected["bytes"] and sha256(body) == expected["sha256"], "LEDGER_SOURCE_TAMPERED")
        replay = {}
        for reference in entry["receipt_references"]:
            receipt = _json(Path(reference).read_bytes())
            require(receipt.get("query", {}).get("data_id") == symbol, "LEDGER_RECEIPT_SYMBOL_MISMATCH")
            if receipt.get("http_status") == 200 and receipt.get("raw_capture_status") == "COMPLETE" and entry["status"] != "ACCESS_FAILED":
                try:
                    material = read_provider_response(reference, symbols=tuple(markets))
                    for row in material["rows"]:
                        replay[(reference, row["json_locator"])] = row
                except Rejected as exc:
                    require(entry["status"] == "VALIDATION_FAILED" and entry["reason"] == str(exc), "LEDGER_REJECTION_REPLAY_MISMATCH")
        for row in entry["rows"]:
            _policy(row)
            require(row["symbol"] == symbol, "LEDGER_ROW_IDENTITY_MISMATCH")
            require(row["market"] == markets[symbol] and row["coverage_plan_id"] == plan["plan_id"], "LEDGER_ROW_MARKET_MISMATCH")
            require(all(field in row and row[field] is None for field in ("filing_id", "revision_id", "public_time")), "UNSUPPORTED_VERSION_CLAIM")
            require(_quarter(row["provider_date"]) == row["analysis_quarter"], "LEDGER_DATE_MISMATCH")
            _decimal(row["provider_value"])
            expected = replay.get((row["receipt_reference"], row["json_locator"]))
            require(expected is not None and all(row[k] == expected[k] for k in core), "LEDGER_RAW_REPLAY_MISMATCH")
            require(_time(row["acquired_observed_at"]) <= _time(row["verified_observed_at"]) <= _time(entry["recorded_at"]), "LEDGER_OBSERVATION_TIME_INVALID")
        quarters = [r["analysis_quarter"] for r in entry["rows"]]
        require(quarters == [q for q in DESCENDING if q in quarters], "LEDGER_QUARTER_ORDER_INVALID")
        require(len(set(quarters)) == len(quarters), "LEDGER_DUPLICATE_QUARTER")
        require({(r["receipt_reference"], r["json_locator"]) for r in entry["rows"]} == set(replay), "LEDGER_VALID_POSITIONS_OMITTED")
        require(entry["status"] in {"COMPLETE", "HISTORICAL_INSUFFICIENT", "NO_EPS", "ACCESS_FAILED", "VALIDATION_FAILED"}, "LEDGER_STATUS_INVALID")
        if entry["status"] == "COMPLETE":
            require(len(quarters) == 8, "LEDGER_COMPLETE_CLAIM_INVALID")
        events[symbol] = entry
    return events


def reuse_original(root, plan, directory):
    events = read_events(root, plan)
    if all(s in events for s in ("2330", "6488", "1340")):
        return
    candidate = build_candidate(directory, plan["code_binding"])
    for company in candidate["companies"]:
        symbol = company["symbol"]
        if symbol in events:
            continue
        rows = company["quarters"]
        refs = sorted({r["receipt_reference"] for r in rows})
        append_event(root, result_entry(plan, symbol, rows, origin="REUSED_ORIGINAL_24",
            references=refs, integrity=candidate["input_integrity"]))


def evaluate_receipt(plan, symbol, reference):
    reference = Path(reference).resolve()
    receipt = _json(reference.read_bytes())
    require(receipt.get("query") == {**QUERY, "data_id": symbol}, "COVERAGE_REQUEST_MISMATCH")
    inventory = {str(reference): {"bytes": reference.stat().st_size, "sha256": sha256(reference.read_bytes())}}
    service_status, access_requirement = None, False
    if receipt.get("raw_path"):
        path = reference.parent.parent / receipt["raw_path"]
        body = path.read_bytes()
        inventory[str(path)] = {"bytes": len(body), "sha256": sha256(body)}
        try:
            payload = _json(body)
            service_status = payload.get("status")
            message = str(payload.get("msg", "")).lower()
            access_requirement = service_status != 200 and any(word in message for word in
                ("permission", "subscribe", "sponsor", "backer", "login", "\u6703\u54e1", "\u8d0a\u52a9"))
        except (Rejected, AttributeError):
            pass
    if receipt.get("error_body_path"):
        path = reference.parent.parent / receipt["error_body_path"]
        body = path.read_bytes()
        require(sha256(body) == receipt["error_body_sha256"], "ERROR_BODY_HASH_MISMATCH")
        inventory[str(path)] = {"bytes": len(body), "sha256": sha256(body)}
    shared = receipt.get("http_status") in SHARED_STATUSES or service_status in SHARED_STATUSES or access_requirement or receipt.get("status") == "TRANSPORT_BLOCKED"
    if receipt.get("http_status") == 200 and receipt.get("raw_capture_status") == "COMPLETE" and (service_status in SHARED_STATUSES or access_requirement):
        try:
            read_provider_response(reference, symbols=tuple(validate_plan(plan)))
        except Rejected as exc:
            if str(exc) != "FINMIND_SCHEMA_INVALID":
                return result_entry(plan, symbol, status="VALIDATION_FAILED", reason=str(exc),
                    references=[str(reference)], integrity=inventory, shared_stop=True)
    if receipt.get("status") in {"HTTP_BLOCKED", "TRANSPORT_BLOCKED"} or service_status in SHARED_STATUSES or access_requirement:
        return result_entry(plan, symbol, status="ACCESS_FAILED", reason={"transport_status": receipt.get("status"),
            "http_status": receipt.get("http_status"), "service_status": service_status,
            "exception_class": receipt.get("exception_class"), "provider_access_requirement_detected": access_requirement}, references=[str(reference)], integrity=inventory, shared_stop=shared)
    try:
        material = read_provider_response(reference, symbols=tuple(validate_plan(plan)))
        return result_entry(plan, symbol, material["rows"], material["issues"], references=[str(reference)], integrity=material["input_integrity"])
    except Rejected as exc:
        return result_entry(plan, symbol, status="VALIDATION_FAILED", reason=str(exc), references=[str(reference)], integrity=inventory)


def scan(root, plan, capture, *, token=None, max_requests=280, max_seconds=3600, interval_seconds=13,
         sleep=time.sleep, clock=time.monotonic, progress=None):
    require(0 <= max_requests <= 1978 and 0 < max_seconds <= 3600 and interval_seconds >= 13, "UNSAFE_SCAN_BUDGET")
    events = read_events(root, plan)
    for event in events.values():
        if event["shared_host_stop"]:
            return {"reason": "PERSISTED_SHARED_HOST_STOP", "symbol": event["symbol"], "new_requests": 0}
    started, requests, last = clock(), 0, None
    for stock in plan["universe"]["stocks"]:
        symbol = stock["symbol"]
        if symbol in events:
            continue
        intent = Path(root) / "intents" / (symbol + ".json")
        reference = Path(root) / "receipts" / ("coverage-" + symbol + ".json")
        if intent.exists():
            saved_intent = _json(intent.read_bytes())
            require(saved_intent["plan_id"] == plan["plan_id"] and saved_intent["symbol"] == symbol, "REQUEST_INTENT_PLAN_MISMATCH")
            if not reference.exists():
                return {"reason": "REQUEST_OUTCOME_UNKNOWN_NO_AUTOMATIC_RETRY", "symbol": symbol, "new_requests": requests}
        else:
            delay = 0 if last is None else max(0, interval_seconds - (clock() - last))
            if requests >= max_requests or clock() - started + delay + 20 >= max_seconds:
                return {"reason": "BOUNDED_BATCH_BUDGET", "new_requests": requests}
            sleep(delay)
            save(intent, {"plan_id": plan["plan_id"], "symbol": symbol, "market": stock["market"],
                          "query": {**QUERY, "data_id": symbol}, "started_at": now()})
            last = clock()
            requests += 1
            capture(Path(root), "coverage-" + symbol, API, symbol, start=QUERY["start_date"], end=QUERY["end_date"], token=token)
        event = append_event(root, evaluate_receipt(plan, symbol, reference))
        events[symbol] = event
        if progress is not None:
            progress({"symbol": symbol, "status": event["status"], "valid_quarters": len(event["rows"]), "new_requests": requests})
        if event["shared_host_stop"]:
            return {"reason": "SHARED_HOST_ACCESS_STOP", "symbol": symbol, "new_requests": requests}
    return {"reason": "ALL_COMPANIES_ACCOUNTED_FOR", "new_requests": requests}


def summary(root, plan, stop):
    events = read_events(root, plan)
    companies, positions = [], []
    for stock in plan["universe"]["stocks"]:
        symbol = stock["symbol"]
        entry = events.get(symbol)
        rows = entry["rows"] if entry else []
        missing = [q for q in DESCENDING if q not in {r["analysis_quarter"] for r in rows}]
        attempted = (Path(root) / "intents" / (symbol + ".json")).exists()
        companies.append({**stock, "plan_id": plan["plan_id"], "status": entry["status"] if entry else
            "REQUEST_OUTCOME_UNKNOWN" if attempted else "NOT_ATTEMPTED", "valid_quarters": len(rows),
            "coverage": f"{len(rows)}/8", "missing_quarters": missing, "unattempted": entry is None and not attempted,
            "reason": entry["reason"] if entry else stop["reason"], "issues": entry["issues"] if entry else [],
            "receipt_references": entry["receipt_references"] if entry else [], "origin": entry["origin"] if entry else None})
        for quarter in DESCENDING:
            row = next((r for r in rows if r["analysis_quarter"] == quarter), None)
            issues = [i for i in entry["issues"] if i.get("analysis_quarter") == quarter and i.get("target_position")] if entry else []
            positions.append({**stock, "analysis_quarter": quarter, "status": "VALID_PROVIDER_CANDIDATE" if row else
                issues[0]["reason"] if issues else "MISSING_EPS" if entry and entry["status"] in {"NO_EPS", "HISTORICAL_INSUFFICIENT"} else
                entry["status"] if entry else "NOT_ATTEMPTED" if not attempted else "REQUEST_OUTCOME_UNKNOWN",
                "candidate": row, "issues": issues})
    rows = [r for event in events.values() for r in event["rows"]]
    total = len(companies)
    complete = sum(c["valid_quarters"] == 8 for c in companies)
    counts = {"universe_listed_count": total, "accounted_for": len(events), "universe_denominator": total,
        "eps_complete_companies": complete, "valid_company_quarters": len(rows), "quarter_denominator": total * 8,
        "unattempted_companies": sum(c["unattempted"] for c in companies), "status_counts": dict(Counter(c["status"] for c in companies)),
        "actual_data_request_intents": len(list((Path(root) / "intents").glob("*.json")))}
    latest = max((_time(r["acquired_observed_at"]) for r in rows), default=None)
    return {"artifact_kind": KIND, "plan_id": plan["plan_id"], "source_policy": POLICY, "counts": counts,
        "window": list(WINDOW), "quarter_order": "LATEST_TO_OLDEST", "stop": stop, "companies": companies,
        "positions": positions, "generated_at": now(), "not_a_simultaneous_market_snapshot": True,
        "latest_necessary_observation_at": latest.isoformat() if latest else None,
        "full_universe_complete_observed_at": latest.isoformat() if complete == total and latest else None,
        "production_eligible": False, "original_eight_quarter_coverage_credit": 0,
        "formal_eight_quarter_acceptance": "NOT_PERFORMED", "historical_pit_status": "UNPROVEN",
        "historical_cutoff": "2026-10-05", "eps_only_not_complete_fundamental_input": True}


def revenue_inventory(source_root, historical_plan_path, universe):
    """Read and replay existing official bytes only; never invoke acquisition."""
    from .full_market_history import digest
    from .sources.mops_raw_evidence import load_response
    from .sources.fundamental_history import _warmup_revenue_rows, _decode_response
    historical = json.loads(Path(historical_plan_path).read_bytes())
    paths = []
    for path in Path(source_root).glob("*/reports/mops/*.json"):
        receipt = json.loads(path.read_bytes())
        if receipt.get("domain") == "revenue" and receipt.get("plan_id") == universe["source_plan_id"]:
            paths.append((path, receipt))
    periods = sorted({r["requested_period"] for _, r in paths})[-3:]
    found, sources, errors, integrity = {}, [], [], {}
    markets = {r["symbol"]: r["market"] for r in universe["stocks"]}
    for path, receipt in paths:
        if receipt["requested_period"] not in periods:
            continue
        reference = {"path": path.relative_to(path.parents[2]).as_posix(), "sha256": digest(receipt)}
        try:
            receipt, body = load_response(path.parents[2], reference, historical)
            require(receipt["http_status"] == 200 and receipt["final_url"] == receipt["endpoint"], "REVENUE_TRANSPORT_INVALID")
            length = receipt.get("content_length")
            require(length is None or int(length) == len(body), "REVENUE_LENGTH_MISMATCH")
            rows, failures = _warmup_revenue_rows(_decode_response(body), receipt["market"], receipt["requested_period"],
                {**receipt, "raw_response_reference": reference})
            raw_path = path.parents[2] / receipt["raw_path"]
            for p in (path, raw_path):
                b = p.read_bytes()
                integrity[str(p)] = {"bytes": len(b), "sha256": sha256(b)}
            sources.append({"market": receipt["market"], "period": receipt["requested_period"],
                "receipt_reference": str(path), "raw_sha256": receipt["body_sha256"], "observed_at": receipt["retrieval_timestamp"],
                "raw_valid_row_count": len(rows), "row_failure_count": len(failures)})
            for row in rows:
                if markets.get(row["symbol"]) == row["market"]:
                    key = (row["symbol"], row["revenue_period"])
                    require(key not in found, "DUPLICATE_REVENUE_REFERENCE")
                    found[key] = {"receipt_reference": str(path), "raw_sha256": receipt["body_sha256"],
                                  "observed_at": receipt["retrieval_timestamp"]}
            errors.extend(failures)
        except (Rejected, RuntimeError, ValueError, OSError) as exc:
            errors.append({"receipt_reference": str(path), "reason": str(exc)})
    companies = [{**r, "available_periods": [p for p in periods if (r["symbol"], p) in found],
        "missing_periods": [p for p in periods if (r["symbol"], p) not in found],
        "references": [found[(r["symbol"], p)] for p in periods if (r["symbol"], p) in found]} for r in universe["stocks"]]
    return {"usage_scope": "READ_ONLY_EXISTING_REVENUE_AVAILABILITY", "periods": periods,
        "period_selection": "LATEST_THREE_PERIODS_PRESENT_IN_BOUND_LOCAL_PLAN_RECEIPTS_NOT_NEW_ANNOUNCEMENT_ANCHOR",
        "complete_three_period_companies": sum(len(c["available_periods"]) == 3 for c in companies) if len(periods) == 3 else 0,
        "valid_company_periods": len(found), "companies": companies, "sources": sources, "failures": errors,
        "input_integrity": integrity, "new_revenue_requests": 0, "historical_pit_acceptance": "NOT_PERFORMED",
        "production_eligible": False}

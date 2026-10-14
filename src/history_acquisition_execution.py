"""Isolated, opt-in history evidence execution. Never ranking, warmup or publication."""
from datetime import date
from pathlib import Path
import re
import subprocess
import time
import traceback
from urllib.parse import urlencode

from .eps_duration_facts.model import require
from .provider_eps_dispatch import DispatchGate, exclusive_scan
from .provider_eps_metadata import read_metadata
from . import session_discovery_execution as evidence
from .fundamental_first_refresh_execution import exact_universe
from .sources.tpex import HISTORICAL_ENDPOINT, INDEX_HISTORY_ENDPOINT
from .history_acquisition_validation import parse_history, benchmark_chains, coverage_inventory

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "RATE_HISTORY_ACQUISITION_WIRING_V1"
CR = "RATE-MH-HISTORY-ACQUISITION-WIRING-001"
UNIVERSE = evidence.UNIVERSE
PLANNING_SHA = "c5478807f9851be605f73b6115e234687cfe18c215fac5e9529279955f553341"
PENDING = "PENDING_CONTROL_CENTER_AUTHORIZATION"
AUTHORIZED = "HISTORY_ACQUISITION_EXECUTION_AUTHORIZED"
SOURCE_OWNERS = {"TWSE": "src/sources/twse.py", "TPEX": "src/sources/tpex.py"}
OWNER_PATHS = [*SOURCE_OWNERS.values(), "src/benchmark_history.py", "src/historical_store.py",
    "scripts/bootstrap_tpex_history.py", "src/history_acquisition_validation.py", "src/history_acquisition_transport.py",
    "src/history_acquisition_execution.py", "src/session_discovery_execution.py", "src/session_discovery_transport.py",
    "src/provider_eps_metadata.py", "src/provider_eps_dispatch.py", "src/fundamental_first_refresh_execution.py",
    "docs/contracts/RATE_HISTORY_ACQUISITION_WIRING_V1.json", "scripts/run_history_acquisition.py"]
ENDPOINTS = {("TWSE", "stock"): "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY",
             ("TWSE", "benchmark"): "https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST",
             ("TPEX", "stock"): HISTORICAL_ENDPOINT, ("TPEX", "benchmark"): INDEX_HISTORY_ENDPOINT}


def owners():
    return {path: evidence.sha((ROOT / path).read_bytes().replace(b"\r\n", b"\n")) for path in OWNER_PATHS}


def request_entry(spec, ordinal):
    require(isinstance(spec, dict) and set(spec) == {"market", "product", "symbol", "period"}, "HISTORY_REQUEST_SPEC_INVALID")
    market, product, symbol, period = (spec[k] for k in ("market", "product", "symbol", "period"))
    require((market, product) in ENDPOINTS and isinstance(period, str) and re.fullmatch(r"\d{6}", period), "HISTORY_REQUEST_SPEC_INVALID")
    try:
        date(int(period[:4]), int(period[4:]), 1)
    except ValueError as exc:
        raise ValueError("HISTORY_REQUEST_PERIOD_INVALID") from exc
    require(isinstance(symbol, str) and symbol if product == "stock" else symbol is None, "HISTORY_REQUEST_SYMBOL_INVALID")
    require(type(ordinal) is int and ordinal >= 1, "HISTORY_REQUEST_ORDINAL_INVALID")
    if market == "TWSE":
        parameters = {"date": period + "01", "response": "json"}
        if product == "stock":
            parameters["stockNo"] = symbol
    else:
        parameters = {"date": period[:4] + "/" + period[4:] + "/01", "response": "json"}
        parameters["code" if product == "stock" else "id"] = symbol if product == "stock" else ""
    endpoint = ENDPOINTS[(market, product)]
    source = market + "_" + product.upper() + "_HISTORY"
    return {**spec, "ordinal": ordinal, "source_id": source, "endpoint": endpoint,
        "method": "GET" if market == "TWSE" else "POST", "parameters": parameters,
        "request_url": endpoint + "?" + urlencode(parameters) if market == "TWSE" else endpoint,
        "request_key": source + ":" + (symbol or "INDEX") + ":" + period,
        "timeout_seconds": 30, "minimum_interval_seconds": 13, "retry": 0, "redirect": False, "fallback": False,
        "credentials": "NONE", "source_owner": SOURCE_OWNERS[market],
        "normalizer": "src/benchmark_history.py::normalize_benchmark" if product == "benchmark" else
            "src/historical_store.py::normalize_stock_record" if market == "TWSE" else "scripts/bootstrap_tpex_history.py::extract_symbol_month_rows"}


def build_plan(main_sha, universe, specs, cutoffs, *, maximum_requests=None, synthetic=False):
    require(isinstance(main_sha, str) and re.fullmatch(r"[0-9a-f]{40}", main_sha), "HISTORY_MAIN_INVALID")
    stocks, uid = exact_universe(universe)
    require(synthetic or uid == UNIVERSE, "HISTORY_UNIVERSE_IDENTITY_MISMATCH")
    require(type(synthetic) is bool and isinstance(cutoffs, dict) and set(cutoffs) == {"TWSE", "TPEX"}, "HISTORY_CUTOFF_INVALID")
    for day in cutoffs.values():
        require(date.fromisoformat(day).isoformat() == day, "HISTORY_CUTOFF_INVALID")
    require(isinstance(specs, list) and 1 <= len(specs) <= 23760, "HISTORY_REQUEST_BUDGET_EXCEEDED")
    market_map = {r["symbol"]: r["market"] for r in stocks}
    checked = [request_entry(s, 1) for s in specs]
    for entry in checked:
        if entry["product"] == "stock":
            require(market_map.get(entry["symbol"]) == entry["market"], "HISTORY_REQUEST_UNIVERSE_MISMATCH")
        require(entry["period"] <= cutoffs[entry["market"]][:7].replace("-", ""), "HISTORY_FUTURE_REQUEST_PERIOD")
        latest = date.fromisoformat(cutoffs[entry["market"]])
        oldest = latest.year * 12 + latest.month - 12
        require(int(entry["period"][:4]) * 12 + int(entry["period"][4:]) - 1 >= oldest, "HISTORY_PERIOD_OUTSIDE_TWELVE_MONTH_CAP")
    ordered = sorted(specs, key=lambda s: (s["product"] != "benchmark", s["market"] != "TWSE", s["symbol"] or "", -int(s["period"])))
    entries = [request_entry(spec, n) for n, spec in enumerate(ordered, 1)]
    require(len({e["request_key"] for e in entries}) == len(entries), "HISTORY_DUPLICATE_REQUEST")
    maximum = len(entries) if maximum_requests is None else maximum_requests
    require(type(maximum) is int and maximum == len(entries), "HISTORY_REQUEST_BUDGET_EXCEEDED")
    return evidence.identified({"artifact_kind": "RATE_HISTORY_ACQUISITION_REQUEST_PLAN_V1", "contract": CONTRACT,
        "cr": CR, "planning_sha256": PLANNING_SHA, "main_sha": main_sha, "universe": stocks, "universe_sha256": uid,
        "owner_sha256_lf": owners(), "source_native_cutoffs": cutoffs, "entries": entries,
        "planned_requests": len(entries), "maximum_authorized_requests": maximum,
        "material_scope": "SYNTHETIC_ONLY" if synthetic else "OFFICIAL_HISTORY_EVIDENCE_ONLY",
        "minimum_interval_seconds": 13, "sequential": True, "single_writer": True, "retry": 0,
        "fallback": False, "redirect": False, "auto_resume": False, "ranking_authorized": False,
        "production_publication_allowed": False, "historical_pit": "UNPROVEN"},
        "rate-history-acquisition-plan-", "plan_id", "plan_sha256")


def validate_plan(plan):
    evidence.verify_identity(plan, "rate-history-acquisition-plan-", "plan_id", "plan_sha256")
    specs = [{k: e[k] for k in ("market", "product", "symbol", "period")} for e in plan["entries"]]
    expected = build_plan(plan["main_sha"], {"verification_status": "PASS", "stocks": plan["universe"]}, specs,
        plan["source_native_cutoffs"], maximum_requests=plan["maximum_authorized_requests"],
        synthetic=plan["material_scope"] == "SYNTHETIC_ONLY")
    require(evidence.canonical(plan) == evidence.canonical(expected), "HISTORY_PLAN_OR_OWNER_DRIFT")


def main_guard(plan):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT).decode().strip()
    require(git("branch", "--show-current") == "main" and git("rev-parse", "HEAD") == git("rev-parse", "origin/main") == plan["main_sha"], "HISTORY_MAIN_DRIFT")
    require(not git("status", "--porcelain", "--untracked-files=all"), "HISTORY_DIRTY_WORKTREE")
    for path, pin in plan["owner_sha256_lf"].items():
        body = subprocess.check_output(["git", "show", plan["main_sha"] + ":" + path], cwd=ROOT)
        require(evidence.sha(body) == pin, "HISTORY_COMMITTED_OWNER_DRIFT")


def build_seal(plan, artifacts_root, consumption_root):
    validate_plan(plan)
    evidence.external_roots(artifacts_root, consumption_root, ROOT)
    return evidence.identified({"artifact_kind": "RATE_HISTORY_ACQUISITION_SEAL_V1", "contract": CONTRACT,
        "plan_id": plan["plan_id"], "plan_sha256": plan["plan_sha256"], "main_sha": plan["main_sha"],
        "universe_sha256": plan["universe_sha256"], "owner_sha256_lf": plan["owner_sha256_lf"],
        "artifacts_root_identity": evidence.root_identity(artifacts_root), "consumption_root_identity": evidence.root_identity(consumption_root),
        "maximum_authorized_requests": plan["maximum_authorized_requests"], "single_use": True,
        "material_scope": plan["material_scope"], "status": "READY_FOR_CONTROL_CENTER_AUTHORIZATION_REVIEW"},
        "rate-history-acquisition-seal-", "seal_id", "seal_sha256")


def candidate_authorization(seal):
    core = {k: v for k, v in seal.items() if k not in ("artifact_kind", "status", "seal_id", "seal_sha256")}
    return evidence.identified({**core, "artifact_kind": "RATE_HISTORY_ACQUISITION_AUTHORIZATION_V1",
        "seal_id": seal["seal_id"], "seal_sha256": seal["seal_sha256"], "status": PENDING},
        "rate-history-acquisition-authorization-", "authorization_id", "authorization_sha256")


def validate_authorization(auth, seal, *, candidate=False):
    evidence.verify_identity(auth, "rate-history-acquisition-authorization-", "authorization_id", "authorization_sha256")
    core = {k: v for k, v in candidate_authorization(seal).items() if k not in ("authorization_id", "authorization_sha256")}
    core["status"] = PENDING if candidate else AUTHORIZED
    require(auth == evidence.identified(core, "rate-history-acquisition-authorization-", "authorization_id", "authorization_sha256"), "HISTORY_AUTHORIZATION_MISMATCH")


def preflight(plan, seal, auth, *, artifacts_root, consumption_root, trusted_authorization_sha256=None, candidate=False, synthetic=False):
    validate_plan(plan)
    require((plan["material_scope"] == "SYNTHETIC_ONLY") is synthetic, "HISTORY_SYNTHETIC_SCOPE_FORBIDDEN")
    if not synthetic:
        main_guard(plan)
    require(seal == build_seal(plan, artifacts_root, consumption_root), "HISTORY_SEAL_DRIFT")
    validate_authorization(auth, seal, candidate=candidate)
    if not candidate:
        require(trusted_authorization_sha256 == auth["authorization_sha256"], "HISTORY_TRUSTED_AUTHORIZATION_PIN_REQUIRED")
    require(not (Path(consumption_root) / (auth["authorization_id"] + ".json")).exists(), "HISTORY_AUTHORIZATION_ALREADY_CONSUMED")


def _binding(plan, auth, entry, head):
    return {"authorization_id": auth["authorization_id"], "plan_id": plan["plan_id"], "plan_sha256": plan["plan_sha256"],
            "ordinal": entry["ordinal"], "request_key": entry["request_key"], "endpoint": entry["request_url"], "previous_ledger_head": head}


def validate_response(receipt, raw, entry, plan):
    require(receipt["http_status"] == 200, "HISTORY_HTTP_FAILURE")
    require(receipt["endpoint"] == entry["endpoint"] and receipt["final_url"] == entry["request_url"]
            and receipt["request_url"] == entry["request_url"] and receipt["redirect_detected"] is False, "HISTORY_ENDPOINT_OR_REDIRECT_MISMATCH")
    require(all(receipt[k] == entry[k] for k in ("ordinal", "request_key", "market", "product", "symbol", "period", "method", "parameters")), "HISTORY_RECEIPT_IDENTITY_MISMATCH")
    require(receipt["owner_sha256_lf"] == plan["owner_sha256_lf"] and receipt["plan_sha256"] == plan["plan_sha256"], "HISTORY_RECEIPT_OWNER_MISMATCH")
    require(type(receipt["retry_count"]) is int and receipt["retry_count"] == 0 and receipt["fallback_used"] is False
            and "json" in receipt["content_type"].lower(), "HISTORY_RECEIPT_POLICY_INVALID")
    require(receipt["raw_sha256"] == evidence.sha(raw) and receipt["bytes"] == len(raw), "HISTORY_RAW_HASH_MISMATCH")
    times = [evidence.stamp(receipt[k]) for k in ("requested_at", "request_started_at", "received_at", "validated_at")]
    require(times == sorted(times) and times[-1] <= evidence.stamp(evidence.now()), "HISTORY_RECEIPT_TIME_INVALID")
    return parse_history(raw, entry, observed_at=receipt["received_at"], cutoff=plan["source_native_cutoffs"][entry["market"]])


def _result(plan, events, requests, head, status):
    return {"artifact_kind": "RATE_HISTORY_ACQUISITION_RESULT_V1", "status": status, "plan_id": plan["plan_id"],
        "plan_sha256": plan["plan_sha256"], "actual_requests": requests, "completed_checkpoints": len(events), "ledger_head": head,
        "coverage": coverage_inventory(plan["universe"], events, plan["source_native_cutoffs"]),
        "retry_count": 0, "fallback": False, "auto_resume": False, "ranking_executions": 0, "production_publications": 0,
        "historical_pit": "UNPROVEN", "original_eight_quarter_coverage_credit": 0,
        "material_scope": plan["material_scope"], "production_eligible": False}


def execute(plan, seal, auth, *, artifacts_root, consumption_root, output_root, trusted_authorization_sha256,
            transport=None, synthetic=False, utc=evidence.now, monotonic=time.monotonic, sleep=time.sleep):
    preflight(plan, seal, auth, artifacts_root=artifacts_root, consumption_root=consumption_root,
        trusted_authorization_sha256=trusted_authorization_sha256, synthetic=synthetic)
    require(not synthetic or transport is not None, "HISTORY_SYNTHETIC_TRANSPORT_REQUIRED")
    require(synthetic or transport is None, "HISTORY_REAL_TRANSPORT_OVERRIDE_FORBIDDEN")
    artifacts, consumption = evidence.external_roots(artifacts_root, consumption_root, ROOT)
    output = evidence.safe(output_root)
    require(output.parent == artifacts and not output.exists(), "HISTORY_EXECUTION_ROOT_MUST_BE_NEW_CHILD")
    artifacts.mkdir(parents=True, exist_ok=True)
    consumption.mkdir(parents=True, exist_ok=True)
    with exclusive_scan(artifacts), exclusive_scan(consumption):
        preflight(plan, seal, auth, artifacts_root=artifacts, consumption_root=consumption,
            trusted_authorization_sha256=trusted_authorization_sha256, synthetic=synthetic)
        record = {"artifact_kind": "RATE_HISTORY_ACQUISITION_CONSUMPTION_V1", "authorization_id": auth["authorization_id"],
            "authorization_sha256": auth["authorization_sha256"], "plan_sha256": plan["plan_sha256"], "seal_sha256": seal["seal_sha256"],
            "execution_root_identity": evidence.root_identity(output), "consumed_at": utc(), "status": "CONSUMED", "auto_resume": False}
        require(evidence.stamp(record["consumed_at"]) <= evidence.stamp(evidence.now()), "HISTORY_FUTURE_CLAIM")
        record["consumption_sha256"] = evidence.sha(record)
        evidence.put_json(consumption / (auth["authorization_id"] + ".json"), record)
        output.mkdir()
        for name, value in (("consumption", record), ("plan", plan), ("seal", seal), ("authorization", auth)):
            evidence.put_json(output / (name + ".json"), value)
        from .history_acquisition_transport import dispatch_once
        capture = transport or dispatch_once
        gate = DispatchGate(13, clock=monotonic, sleep=sleep, utc=utc, prior_dispatch=True)
        head, previous, events, requests = None, None, [], 0
        for entry in plan["entries"]:
            intent, raw_ref, receipt_ref = None, None, None
            try:
                require(requests < auth["maximum_authorized_requests"], "HISTORY_REQUEST_BUDGET_EXCEEDED")
                if not synthetic:
                    main_guard(plan)
                require(owners() == plan["owner_sha256_lf"], "HISTORY_OWNER_DRIFT")
                binding = _binding(plan, auth, entry, head)
                dispatch = gate.boundary(binding)
                dispatch_check(dispatch, binding, previous)
                intent = evidence.identified({"artifact_kind": "RATE_HISTORY_ACQUISITION_INTENT_V1", **binding,
                    "requested_at": utc(), "entry": entry, "dispatch": dispatch, "dispatch_sha256": evidence.sha(dispatch)},
                    "rate-history-acquisition-intent-", "intent_id", "intent_sha256")
                evidence.put_json(output / "intents" / f"{entry['ordinal']:05}.json", intent)
                gate.check_outbound(dispatch)
                started = utc()
                requests += 1
                response = capture(entry)
                received = utc()
                gate.completed()
                raw = response["raw_bytes"]
                require(isinstance(raw, bytes), "HISTORY_RAW_BYTES_REQUIRED")
                raw_ref = evidence.object_put(output, "raw", raw)
                receipt = {"artifact_kind": "RATE_HISTORY_ACQUISITION_RECEIPT_V1", **{k: entry[k] for k in
                    ("ordinal", "request_key", "market", "product", "symbol", "period", "endpoint", "request_url", "method", "parameters")},
                    "intent_id": intent["intent_id"], "intent_sha256": intent["intent_sha256"], "plan_sha256": plan["plan_sha256"],
                    "owner_sha256_lf": plan["owner_sha256_lf"], "requested_at": intent["requested_at"], "request_started_at": started,
                    "received_at": received, "validated_at": utc(), "http_status": response["http_status"],
                    "final_url": response["final_url"], "content_type": response["content_type"], "bytes": len(raw), "raw_sha256": evidence.sha(raw),
                    "redirect_detected": bool(response.get("location")) or response["final_url"] != entry["request_url"] or 300 <= response["http_status"] < 400,
                    "retry_count": 0, "fallback_used": False}
                receipt_ref = evidence.object_put(output, "receipts", evidence.canonical(receipt))
                validation = validate_response(receipt, raw, entry, plan)
                event = evidence.identified({"artifact_kind": "RATE_HISTORY_ACQUISITION_VALIDATION_EVENT_V1", **binding,
                    "market": entry["market"], "product": entry["product"], "symbol": entry["symbol"], "period": entry["period"],
                    "intent_sha256": intent["intent_sha256"], "raw": raw_ref, "receipt": receipt_ref, "validation": validation},
                    "rate-history-acquisition-event-", "event_id", "event_sha256")
                benchmark_chains([*events, event])
                evidence.put_json(output / "events" / f"{entry['ordinal']:05}.json", event)
                events.append(event)
                head = event["event_sha256"]
                evidence.put_json(output / "checkpoints" / f"{entry['ordinal']:05}.json", {
                    "plan_id": plan["plan_id"], "completed_ordinals": list(range(1, entry["ordinal"] + 1)), "ledger_head": head, "auto_resume": False})
                previous = dispatch
            except Exception as error:
                reason = "HISTORY_TIMEOUT_UNKNOWN_OUTCOME" if isinstance(error, TimeoutError) else str(error) if str(error).startswith("HISTORY_") else "HISTORY_UNKNOWN_OUTCOME_OR_TOOL_ERROR:" + type(error).__name__
                stop = {"reason": reason, "ordinal": entry["ordinal"], "actual_requests": requests, "completed_checkpoints": len(events),
                    "authorization_status": "CONSUMED", "intent_sha256": intent["intent_sha256"] if intent else None,
                    "raw": raw_ref, "receipt": receipt_ref, "previous_ledger_head": head, "auto_resume": False}
                stop["stop_sha256"] = evidence.sha(stop)
                evidence.put_json(output / "STOP.json", stop)
                evidence.put(output / "traceback.txt", traceback.format_exc().encode("utf-8"))
                break
        result = _result(plan, events, requests, head, "PASS" if len(events) == len(plan["entries"]) else "STOPPED")
        evidence.put_json(output / "RESULT.json", result)
        replay(output, plan, seal, auth, consumption)
        return result


def dispatch_check(value, binding, previous):
    if previous is None:
        from .provider_eps_metadata import number
        require(value["request_identity"] == binding and value["prior_session_continuity"] == "UNPROVEN_CONSERVATIVE_WAIT"
                and value["measurement_boundary"] == "CAPTURE_CALL_NOT_HTTP_WIRE_START" and value["minimum_interval_seconds"] == 13,
                "HISTORY_FIRST_DISPATCH_INVALID")
        require(value["clock_domain"] == "PROCESS_SESSION:" + value["session_identity"], "HISTORY_DISPATCH_SESSION_INVALID")
        elapsed = number(value["monotonic_timestamp"]) - number(value["previous_wait_anchor_monotonic"])
        require(elapsed >= 13 and number(value["actual_wait_seconds"]) <= elapsed
                and value["previous_dispatch_interval_seconds"] is None, "HISTORY_DISPATCH_INTERVAL_INVALID")
        evidence.stamp(value["utc_timestamp"])
    else:
        evidence.dispatch_check(value, binding, previous)


def replay(root, plan, seal, auth, consumption_root):
    root = evidence.safe(root)
    validate_plan(plan)
    require(seal == build_seal(plan, root.parent, consumption_root), "HISTORY_REPLAY_SEAL_DRIFT")
    validate_authorization(auth, seal)
    for name, value in (("plan", plan), ("seal", seal), ("authorization", auth)):
        require((root / (name + ".json")).read_bytes() == evidence.canonical(value), "HISTORY_REPLAY_BINDING_TAMPER")
    record = read_metadata((root / "consumption.json").read_bytes())
    require((Path(consumption_root) / (auth["authorization_id"] + ".json")).read_bytes() == evidence.canonical(record), "HISTORY_CONSUMPTION_TAMPER")
    require(record["consumption_sha256"] == evidence.sha({k: v for k, v in record.items() if k != "consumption_sha256"})
            and record["authorization_id"] == auth["authorization_id"] and record["authorization_sha256"] == auth["authorization_sha256"]
            and record["plan_sha256"] == plan["plan_sha256"] and record["seal_sha256"] == seal["seal_sha256"]
            and record["execution_root_identity"] == evidence.root_identity(root) and record["status"] == "CONSUMED", "HISTORY_CONSUMPTION_TAMPER")
    require((root / "RESULT.json").is_file(), "HISTORY_UNKNOWN_OUTCOME_NO_RESUME")
    result = read_metadata((root / "RESULT.json").read_bytes())
    intents = sorted((root / "intents").glob("*.json"))
    event_paths = sorted((root / "events").glob("*.json"))
    require(len(event_paths) <= len(intents) <= len(plan["entries"]), "HISTORY_LEDGER_SEQUENCE_INVALID")
    head, previous, events = None, None, []
    references = {"raw": set(), "receipts": set()}
    stop = read_metadata((root / "STOP.json").read_bytes()) if (root / "STOP.json").exists() else None
    for n, path in enumerate(intents, 1):
        require(path.name == f"{n:05}.json", "HISTORY_INTENT_SEQUENCE_INVALID")
        intent = read_metadata(path.read_bytes())
        evidence.verify_identity(intent, "rate-history-acquisition-intent-", "intent_id", "intent_sha256")
        entry = plan["entries"][n - 1]
        binding = _binding(plan, auth, entry, head)
        require(all(intent[k] == v for k, v in binding.items()) and intent["entry"] == entry
                and intent["dispatch_sha256"] == evidence.sha(intent["dispatch"]), "HISTORY_INTENT_TAMPER")
        require(evidence.stamp(record["consumed_at"]) <= evidence.stamp(intent["requested_at"]) <= evidence.stamp(evidence.now()), "HISTORY_INTENT_TIME_INVALID")
        dispatch_check(intent["dispatch"], binding, previous)
        previous = intent["dispatch"]
        completed = n <= len(event_paths)
        if completed:
            event_path = event_paths[n - 1]
            require(event_path.name == f"{n:05}.json", "HISTORY_EVENT_SEQUENCE_INVALID")
            event = read_metadata(event_path.read_bytes())
            evidence.verify_identity(event, "rate-history-acquisition-event-", "event_id", "event_sha256")
            require(all(event[k] == v for k, v in binding.items()) and event["intent_sha256"] == intent["intent_sha256"]
                    and all(event[k] == entry[k] for k in ("market", "product", "symbol", "period")), "HISTORY_EVENT_TAMPER")
            refs = event
        else:
            require(stop is not None and n == len(intents), "HISTORY_UNKNOWN_OUTCOME_STOP_REQUIRED")
            refs = stop
        bodies = {}
        for key, family, suffix in (("raw", "raw", ".bin"), ("receipt", "receipts", ".json")):
            ref = refs[key]
            if ref is None:
                require(not completed, "HISTORY_REFERENCE_REQUIRED")
                continue
            require(ref["path"] == family + "/" + ref["sha256"] + suffix, "HISTORY_REFERENCE_INVALID")
            body = (root / ref["path"]).read_bytes()
            require(evidence.sha(body) == ref["sha256"] and len(body) == ref["bytes"], "HISTORY_EVIDENCE_TAMPER")
            references[family].add(ref["path"])
            bodies[key] = body
        if completed:
            receipt = read_metadata(bodies["receipt"])
            require(receipt["intent_id"] == intent["intent_id"] and receipt["intent_sha256"] == intent["intent_sha256"]
                    and receipt["requested_at"] == intent["requested_at"], "HISTORY_RECEIPT_INTENT_MISMATCH")
            require(event["validation"] == validate_response(receipt, bodies["raw"], entry, plan), "HISTORY_VALIDATION_TAMPER")
            events.append(event)
            head = event["event_sha256"]
            expected = {"plan_id": plan["plan_id"], "completed_ordinals": list(range(1, n + 1)), "ledger_head": head, "auto_resume": False}
            require(read_metadata((root / "checkpoints" / f"{n:05}.json").read_bytes()) == expected, "HISTORY_CHECKPOINT_TAMPER")
    require(type(result["actual_requests"]) is int and len(events) <= result["actual_requests"] <= len(intents)
            and result["actual_requests"] <= auth["maximum_authorized_requests"], "HISTORY_REPLAY_REQUEST_BUDGET_INVALID")
    expected_status = "PASS" if len(events) == len(plan["entries"]) else "STOPPED"
    require(result == _result(plan, events, result["actual_requests"], head, expected_status), "HISTORY_RESULT_TAMPER")
    require(len(list((root / "checkpoints").glob("*.json"))) == len(events), "HISTORY_CHECKPOINT_SEQUENCE_INVALID")
    for family in references:
        require({str(p.relative_to(root)).replace("\\", "/") for p in (root / family).glob("*")} == references[family], "HISTORY_ORPHAN_OBJECT_OR_TRUNCATION")
    if stop is not None:
        require(expected_status == "STOPPED" and stop["stop_sha256"] == evidence.sha({k: v for k, v in stop.items() if k != "stop_sha256"})
                and stop["authorization_status"] == "CONSUMED" and stop["auto_resume"] is False
                and stop["ordinal"] == len(events) + 1 and stop["completed_checkpoints"] == len(events)
                and stop["actual_requests"] == result["actual_requests"] and stop["previous_ledger_head"] == head
                and stop["intent_sha256"] == (intent["intent_sha256"] if len(intents) > len(events) else None), "HISTORY_STOP_TAMPER")
    else:
        require(expected_status == "PASS" and len(intents) == len(events) == result["actual_requests"], "HISTORY_FINAL_SEQUENCE_INVALID")
    return result


def resume(*args, **kwargs):
    require(False, "HISTORY_RESUME_FORBIDDEN_FRESH_AUTHORIZATION_REQUIRED")

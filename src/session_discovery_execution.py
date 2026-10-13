"""Opt-in single-use discovery evidence only. Never publishes or calls ranking."""
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time
import traceback
from zoneinfo import ZoneInfo

from .eps_duration_facts.model import require
from .provider_eps_dispatch import DispatchGate, exclusive_scan
from .provider_eps_metadata import read_metadata, _object, _constant, _finite, number
from .sources.tpex import BENCHMARK_ENDPOINT, CURRENT_DAILY_ENDPOINT

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE = "18ff7df30b80df8082efd94f71c894b23da5cc87f945a5fd889d5d92dfc3d43e"
CONTRACT = "RATE_SESSION_DISCOVERY_EXECUTION_V1"
AUTHORIZED = "SESSION_DISCOVERY_EXECUTION_AUTHORIZED"
PENDING = "PENDING_CONTROL_CENTER_AUTHORIZATION"
OWNERS = {"executor": "src/session_discovery_execution.py",
          "transport": "src/session_discovery_transport.py"}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stamp(value):
    require(isinstance(value, str), "DISCOVERY_TIME_INVALID")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.tzinfo is not None, "DISCOVERY_TIME_INVALID")
    return parsed


def identified(core, prefix, id_field, hash_field):
    digest = sha(core)
    return {**core, id_field: prefix + digest, hash_field: digest}


def verify_identity(value, prefix, id_field, hash_field):
    require(isinstance(value, dict), "DISCOVERY_OBJECT_REQUIRED")
    core = {k: v for k, v in value.items() if k not in (id_field, hash_field)}
    require(value == identified(core, prefix, id_field, hash_field), "DISCOVERY_IDENTITY_MISMATCH")
    return core


def targets():
    routes = [("TWSE", "benchmark", "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"),
              ("TWSE", "market_daily", "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL"),
              ("TPEX", "benchmark", BENCHMARK_ENDPOINT),
              ("TPEX", "market_daily", CURRENT_DAILY_ENDPOINT)]
    return [{"ordinal": n, "request_key": market + ":" + product, "market": market,
             "product": product, "endpoint": url, "method": "GET", "timeout": 30,
             "minimum_interval_seconds": 13, "retry": 0, "fallback": False,
             "redirect": False, "credentials": "NONE"}
            for n, (market, product, url) in enumerate(routes, 1)]


def build_plan(main_sha):
    require(isinstance(main_sha, str) and re.fullmatch(r"[0-9a-f]{40}", main_sha), "DISCOVERY_MAIN_INVALID")
    return identified({"artifact_kind": "SESSION_DISCOVERY_REQUEST_PLAN", "contract": CONTRACT,
        "main_sha": main_sha, "ranking_universe_identity": UNIVERSE, "entries": targets(),
        "planned_requests": 4, "maximum_requests": 4, "sequential": True, "single_writer": True,
        "auto_resume": False, "token_required": False}, "rate-session-discovery-plan-", "plan_id", "plan_sha256")


def validate_plan(plan):
    require(isinstance(plan, dict) and canonical(plan) == canonical(build_plan(plan.get("main_sha"))), "DISCOVERY_PLAN_MISMATCH")


def safe(path):
    path = Path(path).absolute()
    require(not any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
                    for p in (path, *path.parents)), "DISCOVERY_LINK_FORBIDDEN")
    return path.resolve()


def root_identity(path):
    return sha({"path": os.path.normcase(str(safe(path)))})


def external_roots(artifacts, consumption, repo=ROOT):
    artifacts, consumption, repo = safe(artifacts), safe(consumption), safe(repo)
    require(not artifacts.is_relative_to(repo) and not consumption.is_relative_to(repo), "DISCOVERY_OUTPUT_IN_REPOSITORY")
    require(artifacts != consumption and not artifacts.is_relative_to(consumption)
            and not consumption.is_relative_to(artifacts), "DISCOVERY_ROOT_OVERLAP")
    # These are discovery-owned, caller-chosen roots, not shared Production directories.
    for path in (artifacts, consumption):
        require(not any((parent / ".git").exists() for parent in (path, *path.parents)),
                "DISCOVERY_OUTPUT_IN_REPOSITORY")
        require(not any(part.lower() in {"artifacts", "production", "state", "portfolio", "ledger", "scheduler"}
                        for part in path.parts), "DISCOVERY_PROTECTED_OUTPUT_ROOT")
    return artifacts, consumption


def owner_hashes(repo=ROOT):
    return {role: sha((Path(repo) / path).read_bytes().replace(b"\r\n", b"\n"))
            for role, path in OWNERS.items()}


def build_seal(plan, artifacts_root, consumption_root, *, repo=ROOT):
    validate_plan(plan)
    artifacts, consumption = external_roots(artifacts_root, consumption_root, repo)
    return identified({"artifact_kind": "SESSION_DISCOVERY_PREEXECUTION_SEAL", "contract": CONTRACT,
        "main_sha": plan["main_sha"], "plan_id": plan["plan_id"], "plan_sha256": plan["plan_sha256"],
        "owner_sha256": owner_hashes(repo), "ranking_universe_identity": UNIVERSE,
        "artifacts_root_identity": root_identity(artifacts),
        "authorization_consumption_root_identity": root_identity(consumption),
        "expected_previous_discovery_latest": None, "maximum_requests": 4, "single_use": True,
        "status": "READY_FOR_CONTROL_CENTER_AUTHORIZATION_REVIEW"},
        "rate-session-discovery-seal-", "seal_id", "seal_sha256")


def candidate_authorization(seal):
    # This API only emits unsigned, non-executable proposals. No authorize() operation.
    binding = {k: v for k, v in seal.items() if k not in ("artifact_kind", "status", "seal_id", "seal_sha256")}
    return identified({**binding, "artifact_kind": "SESSION_DISCOVERY_AUTHORIZATION",
        "preexecution_seal_id": seal["seal_id"], "preexecution_seal_sha256": seal["seal_sha256"],
        "status": PENDING}, "rate-session-discovery-authorization-", "authorization_id", "authorization_sha256")


def validate_authorization(authorization, seal, *, candidate=False):
    verify_identity(authorization, "rate-session-discovery-authorization-", "authorization_id", "authorization_sha256")
    expected = candidate_authorization(seal)
    core = {k: v for k, v in expected.items() if k not in ("authorization_id", "authorization_sha256")}
    core["status"] = PENDING if candidate else AUTHORIZED
    require(canonical(authorization) == canonical(identified(core, "rate-session-discovery-authorization-", "authorization_id", "authorization_sha256")),
            "DISCOVERY_AUTHORIZATION_MISMATCH")


def main_guard(plan, repo=ROOT):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=repo).decode().strip()
    require(git("branch", "--show-current") == "main", "DISCOVERY_MAIN_BRANCH_REQUIRED")
    require(git("rev-parse", "HEAD") == git("rev-parse", "origin/main") == plan["main_sha"], "DISCOVERY_MAIN_DRIFT")
    require(not git("status", "--porcelain", "--untracked-files=all"), "DISCOVERY_DIRTY_WORKTREE")
    for path in OWNERS.values():
        committed = subprocess.check_output(["git", "show", plan["main_sha"] + ":" + path], cwd=repo)
        require(sha(committed) == sha((Path(repo) / path).read_bytes().replace(b"\r\n", b"\n")), "DISCOVERY_OWNER_DRIFT")


def preflight(plan, seal, authorization, *, artifacts_root, consumption_root, repo=ROOT, candidate=False):
    validate_plan(plan)
    main_guard(plan, repo)
    require(canonical(seal) == canonical(build_seal(plan, artifacts_root, consumption_root, repo=repo)), "DISCOVERY_SEAL_OR_OWNER_DRIFT")
    validate_authorization(authorization, seal, candidate=candidate)
    require(not (safe(artifacts_root) / "SESSION_DISCOVERY_LATEST.json").exists(), "DISCOVERY_PREVIOUS_LATEST_DRIFT")
    require(not (safe(consumption_root) / (authorization["authorization_id"] + ".json")).exists(), "AUTHORIZATION_ALREADY_CONSUMED")


def sync_dir(path):
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def put(path, body):
    path = safe(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # A partial record after a crash stays occupied. Never repair or reuse it.
    with path.open("xb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    sync_dir(path.parent)
    return sha(body)


def put_json(path, value):
    return put(path, canonical(value))


def object_put(root, family, body):
    relative = family + "/" + sha(body) + (".bin" if family == "raw" else ".json")
    path = safe(root) / relative
    if path.exists():
        require(path.read_bytes() == body, "DISCOVERY_OBJECT_TAMPER")
    else:
        put(path, body)
    return {"path": relative, "sha256": sha(body), "bytes": len(body)}


def claim(plan, seal, authorization, *, artifacts_root, consumption_root, output_root, utc=now, repo=ROOT):
    preflight(plan, seal, authorization, artifacts_root=artifacts_root, consumption_root=consumption_root, repo=repo)
    artifacts, consumption = external_roots(artifacts_root, consumption_root, repo)
    output = safe(output_root)
    require(output.parent == artifacts and not output.exists(), "DISCOVERY_EXECUTION_ROOT_MUST_BE_NEW_CHILD")
    consumed_at = utc()
    require(stamp(consumed_at) <= stamp(now()), "DISCOVERY_FUTURE_CLAIM")
    record = {"artifact_kind": "SESSION_DISCOVERY_CONSUMPTION", "authorization_id": authorization["authorization_id"],
              "authorization_sha256": authorization["authorization_sha256"], "seal_sha256": seal["seal_sha256"],
              "plan_sha256": plan["plan_sha256"], "execution_root_identity": root_identity(output),
              "consumed_at": consumed_at, "status": "CONSUMED", "auto_resume": False}
    record["consumption_sha256"] = sha(record)
    artifacts.mkdir(parents=True, exist_ok=True)
    try:
        put_json(consumption / (authorization["authorization_id"] + ".json"), record)
    except FileExistsError:
        require(False, "AUTHORIZATION_ALREADY_CONSUMED")
    output.mkdir()
    put_json(output / "consumption.json", record)
    return record


def session_date(value):
    require(isinstance(value, str), "DISCOVERY_SESSION_DATE_INVALID")
    if re.fullmatch(r"\d{8}", value):
        return date(int(value[:4]), int(value[4:6]), int(value[6:])).isoformat()
    if re.fullmatch(r"\d{7}", value):
        return date(int(value[:3]) + 1911, int(value[3:5]), int(value[5:])).isoformat()
    match = re.fullmatch(r"(\d{3}|\d{4})[-/](\d{2})[-/](\d{2})", value)
    require(match is not None, "DISCOVERY_SESSION_DATE_INVALID")
    y, m, d = map(int, match.groups())
    return date(y + 1911 if y < 1000 else y, m, d).isoformat()


def response_session(body, entry, observed_at):
    payload = json.loads(body.decode("utf-8-sig"), object_pairs_hook=_object, parse_constant=_constant)
    _finite(payload)
    dates, locators = [], []
    if entry["market"] == "TWSE":
        require(isinstance(payload, dict) and payload.get("stat") == "OK", "DISCOVERY_SCHEMA_INVALID")
        dates.append(session_date(payload.get("date")))
        tables = payload.get("tables") if entry["product"] == "benchmark" else [payload]
        require(isinstance(tables, list) and tables, "DISCOVERY_SCHEMA_INVALID")
        matching = []
        for i, table in enumerate(tables):
            require(isinstance(table, dict), "DISCOVERY_SCHEMA_INVALID")
            fields, rows = table.get("fields"), table.get("data")
            require(isinstance(fields, list) and len(set(fields)) == len(fields) and isinstance(rows, list), "DISCOVERY_SCHEMA_INVALID")
            required = {"指數", "收盤指數"} if entry["product"] == "benchmark" else {"證券代號", "收盤價"}
            if not required <= set(fields):
                continue
            for j, row in enumerate(rows):
                require(isinstance(row, list) and len(row) == len(fields), "DISCOVERY_SCHEMA_INVALID")
                if entry["product"] == "benchmark":
                    if row[fields.index("指數")] != "發行量加權股價指數":
                        continue
                matching.append(row)
                locators.append(f"$.tables[{i}].data[{j}]" if entry["product"] == "benchmark" else f"$.data[{j}]")
        require(matching and (entry["product"] != "benchmark" or len(matching) == 1), "DISCOVERY_SCHEMA_INVALID")
        rows_count = len(matching)
    else:
        require(isinstance(payload, list) and payload, "DISCOVERY_SCHEMA_INVALID")
        for i, row in enumerate(payload):
            require(isinstance(row, dict) and "Date" in row, "DISCOVERY_SCHEMA_INVALID")
            if entry["product"] == "market_daily":
                require("SecuritiesCompanyCode" in row and isinstance(row["SecuritiesCompanyCode"], str)
                        and row["SecuritiesCompanyCode"] and ("Close" in row or "ClosingPrice" in row), "DISCOVERY_SCHEMA_INVALID")
            else:
                require(any(k in row for k in ("ClosingIndex", "收市", "收盤指數", "收盤價", "close")), "DISCOVERY_SCHEMA_INVALID")
            dates.append(session_date(row["Date"]))
            locators.append(f"$[{i}]")
        rows_count = len(payload)
        if entry["product"] == "market_daily":
            require(len(set(dates)) == 1, "DISCOVERY_SESSION_IDENTITY_INVALID")
    observed = stamp(observed_at).astimezone(ZoneInfo("Asia/Taipei"))
    require(max(dates) <= observed.date().isoformat(), "DISCOVERY_FUTURE_SESSION")
    require(max(dates) != observed.date().isoformat() or observed.hour * 60 + observed.minute >= 13 * 60 + 30,
            "DISCOVERY_PRE_CLOSE_SESSION")
    return {"latest_session": max(dates), "recognized_dates": sorted(set(dates)),
            "row_count": rows_count, "json_locators": locators, "validation": "PASS",
            "scope": "SESSION_DISCOVERY_ONLY_NOT_180_SESSION_CALENDAR"}


def validate_response(receipt, raw, entry):
    require(receipt["http_status"] == 200, "STOP_REDIRECT_FORBIDDEN" if 300 <= receipt["http_status"] < 400 else "STOP_HTTP_FAILURE")
    require(receipt["final_url"] == entry["endpoint"] and not receipt["redirect_detected"], "STOP_REDIRECT_FORBIDDEN")
    require(receipt["endpoint"] == entry["endpoint"] and receipt["market"] == entry["market"]
            and receipt["product"] == entry["product"], "DISCOVERY_SOURCE_IDENTITY_MISMATCH")
    require(receipt["raw_sha256"] == sha(raw) and receipt["bytes"] == len(raw), "DISCOVERY_RAW_HASH_MISMATCH")
    require(receipt["fallback_used"] is False and type(receipt["retry_count"]) is int
            and receipt["retry_count"] == 0 and "json" in receipt["content_type"].lower(), "DISCOVERY_RECEIPT_INVALID")
    require(stamp(receipt["requested_at"]) <= stamp(receipt["received_at"]) <= stamp(receipt["validated_at"]) <= stamp(now()),
            "DISCOVERY_RECEIPT_TIME_INVALID")
    return response_session(raw, entry, receipt["received_at"])


def dispatch_check(evidence, binding, previous=None):
    require(evidence["request_identity"] == binding and evidence["minimum_interval_seconds"] == 13
            and evidence["measurement_boundary"] == "CAPTURE_CALL_NOT_HTTP_WIRE_START", "DISCOVERY_DISPATCH_BINDING")
    require(evidence["clock_domain"] == "PROCESS_SESSION:" + evidence["session_identity"], "DISCOVERY_DISPATCH_SESSION")
    t, wait = number(evidence["monotonic_timestamp"]), number(evidence["actual_wait_seconds"])
    stamp(evidence["utc_timestamp"])
    anchor = evidence["previous_wait_anchor_monotonic"]
    if previous is None:
        require(anchor is None and evidence["previous_dispatch_interval_seconds"] is None
                and evidence["prior_session_continuity"] == "NO_PRIOR_DISPATCH", "DISCOVERY_DISPATCH_FIRST")
    else:
        require(evidence["session_identity"] == previous["session_identity"]
                and evidence["prior_session_continuity"] == "SAME_MONOTONIC_DOMAIN", "DISCOVERY_DISPATCH_SESSION")
        elapsed = t - number(anchor)
        gap = t - number(previous["monotonic_timestamp"])
        require(number(anchor) >= previous["monotonic_timestamp"] and elapsed >= 13 and gap >= 13 and wait <= elapsed
                and math.isclose(gap, number(evidence["previous_dispatch_interval_seconds"]), rel_tol=0, abs_tol=1e-6),
                "DISCOVERY_DISPATCH_INTERVAL")


def execute(plan, seal, authorization, *, artifacts_root, consumption_root, output_root, repo=ROOT,
            transport=None, utc=now, monotonic=time.monotonic, sleep=time.sleep):
    preflight(plan, seal, authorization, artifacts_root=artifacts_root, consumption_root=consumption_root, repo=repo)
    artifacts, consumption = external_roots(artifacts_root, consumption_root, repo)
    artifacts.mkdir(parents=True, exist_ok=True)
    consumption.mkdir(parents=True, exist_ok=True)
    # Separate discovery-owned OS lock; does not touch any coverage/Production lock.
    with exclusive_scan(artifacts), exclusive_scan(consumption):
        claim(plan, seal, authorization, artifacts_root=artifacts, consumption_root=consumption,
              output_root=output_root, utc=utc, repo=repo)
        root = safe(output_root)
        put_json(root / "plan.json", plan)
        put_json(root / "seal.json", seal)
        put_json(root / "authorization.json", authorization)
        from .session_discovery_transport import dispatch_once
        capture = transport or dispatch_once
        gate = DispatchGate(13, clock=monotonic, sleep=sleep, utc=utc)
        ledger_head, completed, requests, previous = None, [], 0, None
        for entry in plan["entries"]:
            intent, raw_ref, receipt_ref = None, None, None
            try:
                main_guard(plan, repo)
                require(owner_hashes(repo) == seal["owner_sha256"], "DISCOVERY_OWNER_DRIFT")
                binding = {"authorization_id": authorization["authorization_id"], "plan_id": plan["plan_id"],
                           "ordinal": entry["ordinal"], "request_key": entry["request_key"],
                           "endpoint": entry["endpoint"], "previous_ledger_head": ledger_head}
                evidence = gate.boundary(binding)
                dispatch_check(evidence, binding, previous)
                requested = utc()
                intent = identified({"artifact_kind": "SESSION_DISCOVERY_INTENT", **binding,
                    "market": entry["market"], "product": entry["product"], "method": "GET",
                    "requested_at": requested, "dispatch": evidence, "dispatch_binding_sha256": sha(evidence)},
                    "rate-session-discovery-intent-", "intent_id", "intent_sha256")
                put_json(root / "intents" / f"{entry['ordinal']:02}.json", intent)
                gate.check_outbound(evidence)
                require(stamp(requested) <= stamp(now()), "DISCOVERY_FUTURE_INTENT")
                requests += 1
                response = capture(entry)
                received = utc()
                gate.completed()
                raw = response["raw_bytes"]
                require(isinstance(raw, bytes), "DISCOVERY_RAW_BYTES_REQUIRED")
                raw_ref = object_put(root, "raw", raw)
                receipt = {"artifact_kind": "SESSION_DISCOVERY_RECEIPT", "intent_id": intent["intent_id"],
                    "endpoint": entry["endpoint"], "final_url": response["final_url"], "http_status": response["http_status"],
                    "content_type": response["content_type"], "bytes": len(raw), "raw_sha256": sha(raw),
                    "requested_at": requested, "received_at": received, "validated_at": utc(),
                    "market": entry["market"], "product": entry["product"],
                    "redirect_detected": response["final_url"] != entry["endpoint"] or bool(response.get("location"))
                        or 300 <= response["http_status"] < 400, "fallback_used": False, "retry_count": 0}
                receipt_ref = object_put(root, "receipts", canonical(receipt))
                validation = validate_response(receipt, raw, entry)
                event = identified({"artifact_kind": "SESSION_DISCOVERY_COMPLETED", **binding,
                    "intent_sha256": intent["intent_sha256"], "raw": raw_ref, "receipt": receipt_ref,
                    "source_validation": validation}, "rate-session-discovery-event-", "event_id", "event_sha256")
                put_json(root / "events" / f"{entry['ordinal']:02}.json", event)
                ledger_head = event["event_sha256"]
                completed.append(event)
                put_json(root / "checkpoints" / f"{entry['ordinal']:02}.json", {
                    "plan_id": plan["plan_id"], "completed_ordinals": list(range(1, entry["ordinal"] + 1)),
                    "ledger_head": ledger_head, "auto_resume": False})
                previous = evidence
            except Exception as error:
                reason = "STOP_TIMEOUT" if isinstance(error, TimeoutError) else str(error)
                if not reason.startswith(("DISCOVERY_", "STOP_", "MONOTONIC_", "DISPATCH_")):
                    reason = "STOP_UNKNOWN_OUTCOME_OR_TOOL_ERROR:" + type(error).__name__
                stop = {"reason": reason, "ordinal": entry["ordinal"],
                    "actual_requests": requests, "completed_checkpoints": len(completed), "authorization_status": "CONSUMED",
                    "intent_sha256": intent["intent_sha256"] if intent else None,
                    "raw": raw_ref, "receipt": receipt_ref, "previous_ledger_head": ledger_head, "auto_resume": False}
                stop["stop_sha256"] = sha(stop)
                put_json(root / "STOP.json", stop)
                put(root / "traceback.txt", traceback.format_exc().encode("utf-8"))
                break
        status = "PASS" if len(completed) == 4 else "STOPPED"
        result = {"artifact_kind": "SESSION_DISCOVERY_RESULT", "status": status, "plan_id": plan["plan_id"],
                  "planned_requests": 4, "actual_requests": requests, "completed_checkpoints": len(completed),
                  "ledger_head": ledger_head, "sessions": {e["request_key"]: e["source_validation"]["latest_session"] for e in completed},
                  "raw_receipt_references": [{"request_key": e["request_key"], "raw": e["raw"], "receipt": e["receipt"]} for e in completed],
                  "retry_count": 0, "fallback": False, "auto_resume": False, "ranking_executions": 0,
                  "publication_count": 0, "calendar_180_ready": False}
        put_json(root / "RESULT.json", result)
        replay(root, plan, seal, authorization, consumption)
        return result


def replay(root, plan, seal, authorization, consumption_root):
    root = safe(root)
    validate_plan(plan)
    verify_identity(seal, "rate-session-discovery-seal-", "seal_id", "seal_sha256")
    validate_authorization(authorization, seal)
    for name, expected in (("plan", plan), ("seal", seal), ("authorization", authorization)):
        require((root / (name + ".json")).read_bytes() == canonical(expected), "DISCOVERY_BINDING_TAMPER")
    record = read_metadata((root / "consumption.json").read_bytes())
    require((safe(consumption_root) / (authorization["authorization_id"] + ".json")).read_bytes() == canonical(record),
            "DISCOVERY_CONSUMPTION_TAMPER")
    require(record["consumption_sha256"] == sha({k: v for k, v in record.items() if k != "consumption_sha256"})
            and record["authorization_id"] == authorization["authorization_id"]
            and record["authorization_sha256"] == authorization["authorization_sha256"]
            and record["seal_sha256"] == seal["seal_sha256"] and record["plan_sha256"] == plan["plan_sha256"]
            and record["execution_root_identity"] == root_identity(root) and record["status"] == "CONSUMED"
            and root_identity(consumption_root) == seal["authorization_consumption_root_identity"], "DISCOVERY_CONSUMPTION_TAMPER")
    result = read_metadata((root / "RESULT.json").read_bytes())
    intents = sorted((root / "intents").glob("*.json"))
    events = sorted((root / "events").glob("*.json"))
    require(len(intents) <= 4 and len(events) <= len(intents), "DISCOVERY_LEDGER_SEQUENCE")
    previous, head, sessions, refs = None, None, {}, []
    for n, path in enumerate(intents, 1):
        require(path.name == f"{n:02}.json", "DISCOVERY_INTENT_SEQUENCE")
        intent = read_metadata(path.read_bytes())
        verify_identity(intent, "rate-session-discovery-intent-", "intent_id", "intent_sha256")
        entry = plan["entries"][n - 1]
        binding = {"authorization_id": authorization["authorization_id"], "plan_id": plan["plan_id"],
                   "ordinal": n, "request_key": entry["request_key"], "endpoint": entry["endpoint"], "previous_ledger_head": head}
        require(all(intent[k] == v for k, v in binding.items()) and intent["market"] == entry["market"]
                and intent["product"] == entry["product"] and intent["method"] == "GET"
                and intent["dispatch_binding_sha256"] == sha(intent["dispatch"]), "DISCOVERY_INTENT_MISMATCH")
        dispatch_check(intent["dispatch"], binding, previous)
        require(stamp(record["consumed_at"]) <= stamp(intent["requested_at"]) <= stamp(now()), "DISCOVERY_INTENT_TIME")
        previous = intent["dispatch"]
        if n > len(events):
            require(n == len(intents) and result["status"] == "STOPPED", "DISCOVERY_UNKNOWN_OUTCOME_STOP_REQUIRED")
            break
        event_path = root / "events" / f"{n:02}.json"
        event = read_metadata(event_path.read_bytes())
        verify_identity(event, "rate-session-discovery-event-", "event_id", "event_sha256")
        require(all(event[k] == v for k, v in binding.items()) and event["intent_sha256"] == intent["intent_sha256"],
                "DISCOVERY_EVENT_BINDING")
        bodies = {}
        for family, suffix in (("raw", ".bin"), ("receipt", ".json")):
            ref = event[family]
            require(ref["path"] == ("raw" if family == "raw" else "receipts") + "/" + ref["sha256"] + suffix,
                    "DISCOVERY_REFERENCE_INVALID")
            body = (root / ref["path"]).read_bytes()
            require(sha(body) == ref["sha256"] and len(body) == ref["bytes"], "DISCOVERY_EVIDENCE_TAMPER")
            bodies[family] = body
        receipt = read_metadata(bodies["receipt"])
        require(receipt["intent_id"] == intent["intent_id"] and receipt["requested_at"] == intent["requested_at"], "DISCOVERY_RECEIPT_INTENT")
        require(event["source_validation"] == validate_response(receipt, bodies["raw"], entry), "DISCOVERY_VALIDATION_TAMPER")
        head = event["event_sha256"]
        checkpoint = read_metadata((root / "checkpoints" / f"{n:02}.json").read_bytes())
        require(checkpoint == {"plan_id": plan["plan_id"], "completed_ordinals": list(range(1, n + 1)),
                               "ledger_head": head, "auto_resume": False}, "DISCOVERY_CHECKPOINT_TAMPER")
        sessions[entry["request_key"]] = event["source_validation"]["latest_session"]
        refs.append({"request_key": event["request_key"], "raw": event["raw"], "receipt": event["receipt"]})
    require(result == {"artifact_kind": "SESSION_DISCOVERY_RESULT", "status": "PASS" if len(events) == 4 else "STOPPED",
        "plan_id": plan["plan_id"], "planned_requests": 4, "actual_requests": result["actual_requests"],
        "completed_checkpoints": len(events), "ledger_head": head, "sessions": sessions,
        "raw_receipt_references": refs, "retry_count": 0, "fallback": False, "auto_resume": False,
        "ranking_executions": 0, "publication_count": 0, "calendar_180_ready": False}, "DISCOVERY_RESULT_TAMPER")
    require(type(result["actual_requests"]) is int and len(events) <= result["actual_requests"] <= len(intents), "DISCOVERY_REQUEST_COUNT")
    require(len(list((root / "checkpoints").glob("*.json"))) == len(events), "DISCOVERY_CHECKPOINT_SEQUENCE")
    if result["status"] == "STOPPED":
        stop = read_metadata((root / "STOP.json").read_bytes())
        require(stop["actual_requests"] == result["actual_requests"] and stop["completed_checkpoints"] == len(events)
                and stop["authorization_status"] == "CONSUMED" and stop["auto_resume"] is False
                and stop["stop_sha256"] == sha({k: v for k, v in stop.items() if k != "stop_sha256"})
                and stop["ordinal"] == len(events) + 1 and stop["previous_ledger_head"] == head
                and stop["intent_sha256"] == (intent["intent_sha256"] if len(intents) > len(events) else None), "DISCOVERY_STOP_TAMPER")
        for family in ("raw", "receipt"):
            ref = stop[family]
            if ref is not None:
                prefix, suffix = ("raw", ".bin") if family == "raw" else ("receipts", ".json")
                require(ref["path"] == prefix + "/" + ref["sha256"] + suffix, "DISCOVERY_REFERENCE_INVALID")
                body = (root / ref["path"]).read_bytes()
                require(sha(body) == ref["sha256"] and len(body) == ref["bytes"], "DISCOVERY_FAILED_EVIDENCE_TAMPER")
    else:
        require(len(intents) == 4 and result["actual_requests"] == 4 and not (root / "STOP.json").exists(), "DISCOVERY_FINAL_SEQUENCE")
    return result


def resume(*args, **kwargs):
    require(False, "DISCOVERY_AUTO_RESUME_FORBIDDEN")

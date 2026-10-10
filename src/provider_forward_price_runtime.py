"""Four bounded official captures and an immutable daily archive, candidate only."""
from datetime import date, timedelta
from pathlib import Path
import math
import traceback
from urllib.request import Request

from .eps_duration_facts.model import require
from .eps_duration_facts.raw import sha256
from .provider_eps_metadata import read_metadata, number as metadata_number
from .provider_eps_candidate import _canonical, _time
from .provider_eps_dispatch import DispatchGate, exclusive_scan, PROTOCOL
from .provider_financial_features import hash_object, instant, within_git_checkout
from .provider_revenue_snapshot import strict_opener
from .provider_shadow_forward import verify, KINDS, replay_chain
from .provider_shadow_forward_prices import periods_between, verified_bytes, endpoint_ok, ArchivedAdapter
from .provider_forward_daily_prices import DAILY, MODE, KIND, TAIPEI, close_at, daily_rows, load_daily_prices, read_payload, benchmark_rows
from .sources.tpex import INDEX_HISTORY_ENDPOINT
from scripts.materialize_production_history_store import _benchmark_month_rows
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "docs/contracts/RATE_FORWARD_PRICE_EVIDENCE_RUNTIME_V1.json"
IDENTITIES = ("src/provider_forward_daily_prices.py", "src/provider_forward_price_runtime.py",
    "src/provider_shadow_forward_prices.py", "src/provider_shadow_forward.py", "src/provider_eps_metadata.py", "src/provider_eps_dispatch.py",
    "scripts/run_provider_shadow_forward.py", "scripts/run_forward_price_runtime.py",
    "docs/contracts/RATE_PROVIDER_SHADOW_FORWARD_VALIDATION_V1.json",
    "scripts/build_production_source_bundle_from_official.py", "scripts/materialize_production_history_store.py",
    "src/sources/twse.py", "src/sources/tpex.py", "config/RATE_PRODUCTION_OFFICIAL_SOURCE_REGISTRY_V1.json")


def put(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(_canonical(value) + b"\n")
    return {"path": str(path), "sha256": sha256(path.read_bytes())}


def pinned(path, digest):
    return read_metadata(verified_bytes(path, digest))


def read_runtime_intent(path, plan):
    value = read_metadata(Path(path).read_bytes())
    require(value["plan_id"] == plan["plan_id"] and value["target"] in plan["targets"] and
        value["request_identity"] == hash_object({"plan_id": plan["plan_id"], "target": value["target"]}), "RUNTIME_INTENT_BINDING_MISMATCH")
    d = value["dispatch"]
    require(value["dispatch_sha256"] == hash_object(d) and d["request_identity"] == value["request_identity"] and
        d["protocol"] == PROTOCOL and d["measurement_boundary"] == "CAPTURE_CALL_NOT_HTTP_WIRE_START" and
        d["clock_domain"] == "PROCESS_SESSION:" + d["session_identity"] and bool(d["session_identity"]), "RUNTIME_DISPATCH_DIGEST_OR_SESSION_INVALID")
    timestamp = metadata_number(d["monotonic_timestamp"])
    interval = metadata_number(d["minimum_interval_seconds"], minimum=13)
    wait = metadata_number(d["actual_wait_seconds"])
    _time(d["utc_timestamp"])
    require(_time(plan["created_at"]) <= _time(d["utc_timestamp"]) <= _time(instant()) and interval == plan["minimum_interval_seconds"], "RUNTIME_DISPATCH_TIME_INVALID")
    anchor, gap, continuity = d["previous_wait_anchor_monotonic"], d["previous_dispatch_interval_seconds"], d["prior_session_continuity"]
    require(anchor is not None and timestamp - metadata_number(anchor) >= interval and wait <= timestamp - anchor,
        "RUNTIME_DISPATCH_ANCHOR_OR_WAIT_INVALID")
    require(continuity == "UNPROVEN_CONSERVATIVE_WAIT" and gap is None or
        continuity == "SAME_MONOTONIC_DOMAIN" and metadata_number(gap, minimum=interval) <= timestamp, "RUNTIME_DISPATCH_CONTINUITY_INVALID")
    return value


def validate_runtime_dispatches(root, plan):
    intents = [read_runtime_intent(p, plan) for p in sorted((Path(root) / "intents").glob("*.json"))]
    require(len({r["request_identity"] for r in intents}) == len(intents), "RUNTIME_DUPLICATE_DISPATCH")
    for prior, current in zip(intents, intents[1:]):
        a, b = prior["dispatch"], current["dispatch"]
        require(a["session_identity"] == b["session_identity"] and b["monotonic_timestamp"] - a["monotonic_timestamp"] >= 13 and
            math.isclose(b["monotonic_timestamp"] - a["monotonic_timestamp"], b["previous_dispatch_interval_seconds"], abs_tol=1e-6),
            "RUNTIME_SESSION_SPACING_INVALID")
    return intents


def baseline_input(baseline_pin, checkpoint_pin, ledger_root):
    snapshot = pinned(baseline_pin["path"], baseline_pin["sha256"])
    cp = pinned(checkpoint_pin["path"], checkpoint_pin["sha256"])
    verify(ledger_root, cp["heads"])
    saved = replay_chain(ledger_root, KINDS[0])
    require(len(saved) == 1 and saved[0]["payload"] == snapshot, "RUNTIME_SINGLE_SEALED_BASELINE_REQUIRED")
    require(not any(e["payload"].get("kind") == "SOURCE_INTEGRITY_FAILURE" for e in replay_chain(ledger_root, KINDS[2])), "RUNTIME_UNRESOLVED_STOP")
    return snapshot, cp


def targets(available_at, day):
    period_list = periods_between(_time(available_at).astimezone(TAIPEI).date().isoformat(), day)
    result = []
    for market in DAILY:
        for period in period_list:
            params = {"date": f"{period[:4]}/{period[4:]}/01", "response": "json", "id": ""}
            endpoint = "https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST?" + urlencode({"date": period + "01", "response": "json"}) if market == "TWSE" else INDEX_HISTORY_ENDPOINT
            result.append({"market": market, "domain": "benchmark", "period": period, "endpoint": endpoint,
                "request_method": "GET" if market == "TWSE" else "POST", "request_params": {} if market == "TWSE" else params})
        result.append({"market": market, "domain": "market_daily", "period": day.replace("-", "")[:6],
            "endpoint": DAILY[market], "request_method": "GET", "request_params": {}})
    return result


def prepare(directory, baseline_pin, checkpoint_pin, ledger_root, binding, day, *, prior_pin=None):
    directory = Path(directory).resolve()
    snapshot, cp = baseline_input(baseline_pin, checkpoint_pin, ledger_root)
    require(not directory.exists() and not within_git_checkout(directory) and not directory.is_relative_to(Path(ledger_root).resolve()), "RUNTIME_NEW_EXTERNAL_ROOT_REQUIRED")
    require(not any(p.casefold() in {"production", "latest", "state", "portfolio", "ledger"} for p in directory.parts), "RUNTIME_PROTECTED_ROOT_FORBIDDEN")
    require(date.fromisoformat(day).isoformat() == day and day == _time(instant()).astimezone(TAIPEI).date().isoformat() and
        _time(snapshot["forward_available_at"]) < _time(close_at(day)), "RUNTIME_LIVE_CURRENT_POST_SEAL_CANDIDATE_REQUIRED")
    require(len(snapshot["companies"]) == 1978 and sum(r["market"] == "TWSE" for r in snapshot["companies"]) == 1085 and
        sum(r["market"] == "TPEX" for r in snapshot["companies"]) == 893, "RUNTIME_REAL_UNIVERSE_IDENTITY")
    if prior_pin:
        from .provider_shadow_forward_prices import load_prices
        previous = load_prices(prior_pin, as_of=instant(), available_at=snapshot["forward_available_at"])
        require(previous.get("calendar_observations") is not None, "RUNTIME_DAILY_PRIOR_MODE_REQUIRED")
    plan = {"artifact_kind": "RATE_FORWARD_PRICE_RUNTIME_REQUEST_PLAN_V1", "runtime_contract_sha256": sha256(CONTRACT_PATH.read_bytes()),
        "execution_binding": binding, "baseline_pin": baseline_pin, "checkpoint_pin": checkpoint_pin,
        "ledger_root": str(Path(ledger_root).resolve()), "shadow_snapshot_id": snapshot["shadow_snapshot_id"],
        "forward_available_at": snapshot["forward_available_at"], "universe_id": snapshot["universe_id"],
        "candidate_date": day, "prior_price_pin": prior_pin, "targets": targets(snapshot["forward_available_at"], day),
        "source_identities": [{"path": str(ROOT / p), "sha256": sha256((ROOT / p).read_bytes())} for p in IDENTITIES],
        "created_at": instant(), "output_root": str(directory), "minimum_interval_seconds": 13,
        "automatic_retries": 0, "max_requests_per_target": 1, "new_shadow_snapshot_allowed": False,
        "production_eligible": False, "decision_eligible": False}
    plan["max_requests"] = len(plan["targets"])
    plan["plan_id"] = "rate-forward-price-runtime-" + hash_object(plan)
    directory.mkdir(parents=True)
    return put(directory / "REQUEST_PLAN.json", plan)


def validate_plan(root, plan_pin):
    plan = pinned(plan_pin["path"], plan_pin["sha256"])
    require(plan["output_root"] == str(Path(root).resolve()) and plan["runtime_contract_sha256"] == sha256(CONTRACT_PATH.read_bytes()), "RUNTIME_PLAN_BINDING_CHANGED")
    require(plan["plan_id"] == "rate-forward-price-runtime-" + hash_object({k: v for k, v in plan.items() if k != "plan_id"}) and
        plan["minimum_interval_seconds"] == 13 and plan["automatic_retries"] == 0 and plan["new_shadow_snapshot_allowed"] is False and
        plan["targets"] == targets(plan["forward_available_at"], plan["candidate_date"]) and plan["max_requests"] == len(plan["targets"]), "RUNTIME_PLAN_TAMPERED")
    for identity in plan["source_identities"]:
        verified_bytes(identity["path"], identity["sha256"])
    return plan


def acquire(root, plan_pin, *, opener=None, gate=None):
    root = Path(root)
    plan = validate_plan(root, plan_pin)
    baseline_input(plan["baseline_pin"], plan["checkpoint_pin"], plan["ledger_root"])
    require(_time(close_at(plan["candidate_date"])) <= _time(instant()), "RUNTIME_PRE_CLOSE_NO_REQUEST")
    require(not (root / "intents").exists() and not (root / "DEFECT_EVIDENCE.json").exists(), "RUNTIME_NO_AUTOMATIC_RETRY_OR_UNKNOWN_OUTCOME")
    gate = gate or DispatchGate(13, prior_dispatch=True, utc=instant)
    opener = opener or strict_opener()
    receipts = []
    dispatches = []
    benchmark_dates = {m: set() for m in DAILY}
    prior_daily = {m: set() for m in DAILY}
    if plan["prior_price_pin"]:
        prior = pinned(plan["prior_price_pin"]["manifest_path"], plan["prior_price_pin"]["manifest_sha256"])
        for item in prior["sources"]:
            receipt = pinned(item["receipt_path"], item["receipt_sha256"])
            if receipt["domain"] == "market_daily":
                day, _ = daily_rows(read_payload(verified_bytes(receipt["raw_path"], receipt["raw_sha256"])), receipt["market"])
                prior_daily[receipt["market"]].add(day)
    with exclusive_scan(root):
        try:
            for i, target in enumerate(plan["targets"]):
                identity = hash_object({"plan_id": plan["plan_id"], "target": target})
                dispatch = gate.boundary(identity)
                intent = {"plan_id": plan["plan_id"], "target": target, "request_identity": identity,
                    "dispatch": dispatch, "dispatch_sha256": hash_object(dispatch)}
                intent_pin = put(root / "intents" / f"{i:04d}.json", intent)
                read_runtime_intent(intent_pin["path"], plan)
                dispatches.append(dispatch)
                gate.check_outbound(dispatch)
                data = urlencode(target["request_params"]).encode() if target["request_method"] == "POST" else None
                request = Request(target["endpoint"], data=data, method=target["request_method"], headers={"User-Agent": "RATE-Data-Engine/1.0", "Accept": "application/json"})
                with opener(request, timeout=45) as response:
                    body = response.read(20_000_001)
                    status, final_url = response.getcode(), response.geturl()
                    content_type = response.headers.get("Content-Type", "")
                    content_length = response.headers.get("Content-Length")
                gate.completed()
                raw_path = root / "raw" / f"{i:04d}.response"
                raw_path.parent.mkdir(exist_ok=True)
                with raw_path.open("xb") as stream:
                    stream.write(body)
                observed = instant()
                receipt = {**target, "http_status": status, "final_url": final_url, "content_type": content_type,
                    "content_length": content_length, "observed_at": observed, "source_validated_at": None,
                    "raw_path": str(raw_path.resolve()), "raw_sha256": sha256(body), "bytes": len(body),
                    "plan_id": plan["plan_id"], "request_identity": identity, "intent_pin": intent_pin,
                    "parser_identity": plan["source_identities"], "automatic_retries": 0}
                try:
                    require(status == 200 and final_url == target["endpoint"] and body and len(body) <= 20_000_000 and
                        (content_length is None or content_length.isdigit() and int(content_length) == len(body)), "RUNTIME_HTTP_REDIRECT_OR_LENGTH_FAILURE")
                    payload = read_payload(body)
                    if target["domain"] == "market_daily":
                        d, _ = daily_rows(payload, target["market"])
                        require(d <= plan["candidate_date"] and _time(close_at(d)) <= _time(observed), "RUNTIME_WRONG_OR_FUTURE_DAILY_DATE")
                        dates = benchmark_dates[target["market"]]
                        require(d in dates or _time(close_at(d)) <= _time(plan["forward_available_at"]), "RUNTIME_DAILY_BENCHMARK_SESSION_MISMATCH")
                        needed = {day for day in dates if _time(close_at(day)) > _time(plan["forward_available_at"])}
                        require(not (needed - prior_daily[target["market"]] - {d}), "RUNTIME_REQUIRED_MARKET_SESSION_MISSING")
                    else:
                        rows = benchmark_rows(receipt, payload, plan["candidate_date"], observed)
                        benchmark_dates[target["market"]].update(row["trade_date"] for row in rows)
                    receipt["source_validated_at"] = instant()
                except Exception:
                    receipt_pin = put(root / "receipts" / f"{i:04d}.json", receipt)
                    receipts.append({"receipt_path": receipt_pin["path"], "receipt_sha256": receipt_pin["sha256"]})
                    raise
                receipt_pin = put(root / "receipts" / f"{i:04d}.json", receipt)
                receipts.append({"receipt_path": receipt_pin["path"], "receipt_sha256": receipt_pin["sha256"]})
            validate_runtime_dispatches(root, plan)
            snapshot, _ = baseline_input(plan["baseline_pin"], plan["checkpoint_pin"], plan["ledger_root"])
            sources = receipts
            if plan["prior_price_pin"]:
                prior = pinned(plan["prior_price_pin"]["manifest_path"], plan["prior_price_pin"]["manifest_sha256"])
                # Replace the monthly session view explicitly; retain every original daily capture.
                sources = [p for p in prior["sources"] if pinned(p["receipt_path"], p["receipt_sha256"])["domain"] == "market_daily"] + receipts
            manifest = {"artifact_kind": KIND, "input_mode": MODE, "generated_at": instant(),
                "sessions_complete_through": plan["candidate_date"], "shadow_snapshot_id": snapshot["shadow_snapshot_id"],
                "baseline_pin": plan["baseline_pin"], "universe_id": snapshot["universe_id"],
                "universe": [{"symbol": r["symbol"], "market": r["market"]} for r in snapshot["companies"]],
                "source_identities": plan["source_identities"], "sources": sources, "parent_price_pin": plan["prior_price_pin"],
                "runtime_execution_binding": plan["execution_binding"], "request_plan_pin": plan_pin,
                "new_shadow_snapshot_allowed": False, "decision_eligible": False, "production_eligible": False}
            # Validate the full material before declaring it a usable archive.
            provisional = {"manifest_path": str(root / "PRICE_MANIFEST.json"), "manifest_sha256": hash_object(manifest)}
            book = load_daily_prices(provisional, manifest, as_of=instant(), available_at=snapshot["forward_available_at"])
            if plan["prior_price_pin"]:
                from .provider_shadow_forward_prices import load_prices
                prior_book = load_prices(plan["prior_price_pin"], as_of=instant(), available_at=snapshot["forward_available_at"])
                for market in DAILY:
                    old = [s["date"] for s in prior_book["sessions"][market]]
                    new = [s["date"] for s in book["sessions"][market]]
                    require(new[:len(old)] == old, "RUNTIME_SESSION_CHAIN_REVISION")
            price_pin = put(root / "PRICE_MANIFEST.json", manifest)
            pin = {"manifest_path": price_pin["path"], "manifest_sha256": price_pin["sha256"]}
            put(root / "SESSION_COVERAGE.json", book["session_coverage"])
            put(root / "SESSION_OBSERVATIONS.json", book["calendar_observations"])
            put(root / "ACQUISITION_RESULT.json", {"status": "PASS", "price_pin": pin, "request_count": len(dispatches),
                "confirmed_sessions": {m: [s["date"] for s in book["sessions"][m]] for m in DAILY},
                "measurement_boundary": "CAPTURE_CALL_NOT_HTTP_WIRE_START", "new_shadow_snapshots": 0})
            return pin
        except Exception as error:
            put(root / "DEFECT_EVIDENCE.json", {"status": "FAIL_CLOSED", "error_type": type(error).__name__,
                "reason": str(error), "traceback": traceback.format_exc(), "requests_dispatched": len(dispatches),
                "saved_receipts": receipts, "request_outcome_unknown": len(receipts) < len(dispatches),
                "stop_reason": "REQUEST_OUTCOME_UNKNOWN_NO_AUTOMATIC_RETRY" if len(receipts) < len(dispatches) else "SOURCE_VALIDATION_FAILED_NO_FALLBACK",
                "no_fallback": True, "no_automatic_retry": True})
            raise

"""Opt-in market-period snapshots reusing MOPS transport, receipts and parser."""
from copy import deepcopy
import math
from pathlib import Path
import traceback
from urllib.error import HTTPError
from urllib.request import build_opener, HTTPRedirectHandler

from .eps_duration_facts.model import require
from .eps_duration_facts.raw import sha256
from .provider_eps_dispatch import DispatchGate, exclusive_scan
from .provider_eps_metadata import read_metadata
from .provider_eps_candidate import _canonical, _time
from .provider_financial_features import CONTRACT, hash_object, instant, within_git_checkout
from .provider_fundamental_shadow_inputs import load_delivery
from .sources.fundamental_history import (MOPS_REVENUE_ARCHIVE, MOPSHistoricalFundamentalAdapter,
    _warmup_revenue_rows, _decode_response, validate_revenue_semantics)
from .sources.mops_raw_evidence import load_response

ROOT = Path(__file__).resolve().parents[1]
MODE = "OFFICIAL_REVENUE_SNAPSHOT_INPUT_V1"
PLAN_KIND = "RATE_OFFICIAL_REVENUE_EXPANSION_REQUEST_PLAN_V1"
SNAPSHOT_KIND = "RATE_OFFICIAL_REVENUE_SNAPSHOT_V1"
PARSER = ROOT / "src/sources/fundamental_history.py"


def put(path, value):
    with Path(path).open("xb") as stream:
        stream.write(_canonical(value) + b"\n")


def endpoint(market, period):
    require(market in ("TWSE", "TPEX") and period in CONTRACT["revenue_months"], "REVENUE_SNAPSHOT_TARGET_OUT_OF_WINDOW")
    year, month = map(int, period.split("-"))
    return MOPS_REVENUE_ARCHIVE.format(market="sii" if market == "TWSE" else "otc", roc_year=year - 1911, month=month)


def plan_core(features, pin, binding, output):
    companies = features["core"]["inputs"]["universe"]["stocks"]
    observations = features["core"]["inputs"]["revenue"]
    targets = []
    for period in reversed(CONTRACT["revenue_months"]):
        for market in ("TWSE", "TPEX"):
            stocks = {c["symbol"] for c in companies if c["market"] == market}
            present = {r["symbol"] for r in observations if r["market"] == market and r["period"] == period}
            missing = sorted(stocks - present)
            old_sources = sorted({(r["receipt_reference"], r["receipt_sha256"], r["raw_reference"], r["raw_sha256"])
                for r in observations if r["market"] == market and r["period"] == period})
            require(len(old_sources) == 1, "REVENUE_SNAPSHOT_OLD_SOURCE_AMBIGUOUS")
            targets.append({"market": market, "period": period, "endpoint": endpoint(market, period),
                "action": "REFRESH_ONCE" if missing else "REUSE_VERIFIED_SUFFICIENT",
                "reason": "MISSING_OBSERVATIONS_NOT_ZERO_BASE" if missing else "ALL_TARGET_OBSERVATIONS_ALREADY_PRESENT",
                "missing_observation_symbols": missing, "old_source": list(old_sources[0])})
    return {"artifact_kind": PLAN_KIND, "input_mode": MODE, "code_binding": binding,
        "old_feature_pin": pin, "old_feature_content_sha256": features["content_sha256"],
        "eps_input_sha256": hash_object(features["core"]["inputs"]["eps"]),
        "gap_input_sha256": hash_object(features["core"]["inputs"]["gaps"]),
        "universe": features["core"]["inputs"]["universe"], "eps_window": CONTRACT["window"],
        "revenue_window": CONTRACT["revenue_months"], "targets": targets,
        "max_new_requests": 6, "max_requests_per_target": 1, "interval_seconds": 13, "automatic_retries": 0,
        "parser_identity": {"path": str(PARSER), "sha256": sha256(PARSER.read_bytes())},
        "transport_identity": {"base_class": "MOPSHistoricalFundamentalAdapter", "method": "_open",
            "strict_opener": "HTTP_REDIRECT_DISABLED_RETURN_ERROR_BODY_TO_EXISTING_CAPTURE",
            "transport_source_sha256": sha256(PARSER.read_bytes()),
            "receipt_source_sha256": sha256((ROOT / "src/sources/mops_raw_evidence.py").read_bytes()),
            "dispatch_source_sha256": sha256((ROOT / "src/provider_eps_dispatch.py").read_bytes())},
        "output_root": str(Path(output).resolve()), "production_eligible": False, "provider_reply_required": False}


def prepare(features, pin, binding, directory):
    directory = Path(directory).resolve()
    require(not directory.exists() and not within_git_checkout(directory), "REVENUE_NEW_EXTERNAL_ROOT_REQUIRED")
    require(not any(p.casefold() in {"production", "latest", "state", "portfolio", "ledger", "data", "artifacts"} for p in directory.parts), "REVENUE_PROTECTED_ROOT_FORBIDDEN")
    for value in (pin.get("delivery_index"), features["core"]["inputs"]["source_binding"].get("coverage_root"),
        features["core"]["inputs"]["source_binding"].get("closeout_manifest_reference")):
        if value:
            source = Path(value).resolve()
            require(not directory.is_relative_to(source if source.is_dir() else source.parent), "REVENUE_ROOT_WITHIN_SOURCE_FORBIDDEN")
    core = plan_core(features, pin, binding, directory)
    plan = {**core, "plan_id": "rate-official-revenue-expansion-" + hash_object(core), "created_at": instant()}
    directory.mkdir(parents=True)
    (directory / "events").mkdir()
    (directory / "intents").mkdir()
    put(directory / "request-plan.json", plan)
    return sha256((directory / "request-plan.json").read_bytes())


def read_plan(root, expected_sha256, features):
    root = Path(root).resolve()
    body = (root / "request-plan.json").read_bytes()
    require(sha256(body) == expected_sha256, "REVENUE_REQUEST_PLAN_TAMPERED")
    plan = read_metadata(body)
    core = plan_core(features, plan["old_feature_pin"], plan["code_binding"], root)
    require({k: v for k, v in plan.items() if k not in {"plan_id", "created_at"}} == core and
        plan["plan_id"] == "rate-official-revenue-expansion-" + hash_object(core), "REVENUE_REQUEST_PLAN_BINDING_MISMATCH")
    require(_time(plan["created_at"]) <= _time(instant()), "REVENUE_PLAN_TIME_FABRICATED")
    return plan


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def strict_opener():
    opener = build_opener(NoRedirect())
    def open_once(request, timeout=45):
        try:
            return opener.open(request, timeout=timeout)
        except HTTPError as response:
            # The existing adapter captures this exact error body and stops on status;
            # returning it prevents its legacy HTTPError redirect-follow branch.
            return response
    return open_once


def observations(root, reference, plan, target, verified_at):
    receipt, body = load_response(root, reference)
    require(receipt["plan_id"] == plan["plan_id"] and receipt["market"] == target["market"] and
        receipt["requested_period"] == target["period"] and receipt["domain"] == "revenue" and
        receipt["parser_sha256"] == plan["parser_identity"]["sha256"], "REVENUE_RECEIPT_BINDING_MISMATCH")
    require(receipt["http_status"] == 200 and receipt["final_url"] == receipt["endpoint"] == target["endpoint"] and
        receipt["body_classification"] == "HTML", "REVENUE_SNAPSHOT_TRANSPORT_INVALID")
    length = receipt.get("content_length")
    require(length is None or str(length).isdigit() and int(length) == len(body), "REVENUE_SNAPSHOT_LENGTH_MISMATCH")
    require(_time(plan["created_at"]) <= _time(receipt["retrieval_timestamp"]) <= _time(verified_at) <= _time(instant()), "REVENUE_OBSERVATION_TIME_INVALID")
    rows, failures = _warmup_revenue_rows(_decode_response(body), target["market"], target["period"],
        {**receipt, "raw_response_reference": reference})
    require(not failures, "REVENUE_SNAPSHOT_ROW_VALIDATION_FAILED")
    markets = {r["symbol"]: r["market"] for r in plan["universe"]["stocks"]}
    result, outside = [], []
    for index, row in enumerate(rows):
        validate_revenue_semantics(row)
        if row["symbol"] not in markets:
            outside.append(row["symbol"])
            continue
        require(markets[row["symbol"]] == row["market"], "REVENUE_UNIVERSE_MARKET_CONFLICT")
        result.append({"symbol": row["symbol"], "market": row["market"], "period": row["revenue_period"],
            "source": row["provider"], "revenue_yoy": str(row["revenue_yoy"]) if row["revenue_yoy"] is not None else None,
            "revenue_yoy_status": row["revenue_yoy_status"], "official_raw_yoy": row["official_raw_yoy"],
            "observed_at": row["retrieval_timestamp"], "source_validated_at": verified_at,
            "receipt_reference": str(Path(root) / reference["path"]), "receipt_sha256": sha256((Path(root) / reference["path"]).read_bytes()),
            "raw_reference": str(Path(root) / receipt["raw_path"]), "raw_sha256": receipt["body_sha256"],
            "row_identity_locator": {"symbol": row["symbol"], "market": row["market"], "period": row["revenue_period"],
                "parsed_row_index_zero_based": index}})
    return result, outside


def target_key(target):
    return target["market"] + "-" + target["period"]


def acquire(root, expected_plan_sha256, features, *, opener=None, gate=None):
    root = Path(root).resolve()
    plan = read_plan(root, expected_plan_sha256, features)
    require(not (root / "SNAPSHOT_MANIFEST.json").exists() and not list((root / "intents").glob("*")) and
        not list((root / "events").glob("*")), "REVENUE_NO_AUTOMATIC_RESTART_OR_RETRY")
    gate = gate or DispatchGate(13, prior_dispatch=True, utc=instant)
    adapter = MOPSHistoricalFundamentalAdapter(opener=opener or strict_opener(), min_interval_seconds=0,
        warmup_evidence_root=root, evidence_context={"plan_id": plan["plan_id"], "purpose": "CANDIDATE_OFFICIAL_REVENUE_ONLY"})
    events, stopped = [], None
    with exclusive_scan(root):
        for target in plan["targets"]:
            key = target_key(target)
            event = {"market": target["market"], "period": target["period"], "endpoint": target["endpoint"],
                "plan_id": plan["plan_id"], "receipt_reference": None, "dispatch": None, "verified_at": None,
                "outside_universe_symbols": [], "source_status": "REUSED_OLD_VERIFIED"}
            if stopped or target["action"] == "REUSE_VERIFIED_SUFFICIENT":
                event["selection_reason"] = "UNATTEMPTED_AFTER_STOP_EXPLICIT_OLD_SELECTION" if stopped else "SUFFICIENT_OLD_RESPONSE"
            else:
                request_id = hash_object({"plan_id": plan["plan_id"], "market": target["market"], "period": target["period"], "endpoint": target["endpoint"]})
                dispatch = gate.boundary(request_id)
                put(root / "intents" / (key + ".json"), {"plan_id": plan["plan_id"], "target": target,
                    "request_identity": request_id, "dispatch": dispatch, "dispatch_sha256": hash_object(dispatch)})
                event["dispatch"] = dispatch
                gate.check_outbound(dispatch)
                previous_diagnostics = len(adapter.diagnostics)
                try:
                    adapter.fetch_revenue_period(target["market"], target["period"])
                    require(len(adapter.diagnostics) == previous_diagnostics + 1, "REVENUE_EXACTLY_ONE_CAPTURE_REQUIRED")
                    diag = adapter.diagnostics[-1]
                    event["receipt_reference"] = diag["raw_response_reference"]
                    event["verified_at"] = instant()
                    _rows, outside = observations(root, event["receipt_reference"], plan, target, event["verified_at"])
                    event.update(source_status="REFRESHED_VERIFIED", outside_universe_symbols=outside,
                        selection_reason="ENTIRE_NEW_RESPONSE_REPLACES_OLD_MARKET_PERIOD")
                except Exception as error:
                    if len(adapter.diagnostics) > previous_diagnostics:
                        event["receipt_reference"] = adapter.diagnostics[-1].get("raw_response_reference")
                    stopped = {"reason": "REQUEST_OR_SOURCE_VALIDATION_FAILED", "target": key,
                        "exception_class": type(error).__name__, "message": str(error)}
                    event.update(source_status="FAILED_NEW_SNAPSHOT_NOT_SELECTED_NO_OLD_FALLBACK", error=stopped)
                    (root / (key + "-traceback.txt")).write_text(traceback.format_exc(), encoding="utf-8")
                finally:
                    gate.completed()
            event["event_sha256"] = hash_object(event)
            put(root / "events" / (key + ".json"), event)
            events.append(event)
        result = {"artifact_kind": SNAPSHOT_KIND, "plan_id": plan["plan_id"], "plan_sha256": expected_plan_sha256,
            "events": events, "stop": stopped or {"reason": "SIX_TARGETS_ACCOUNTED_FOR"},
            "new_revenue_requests": sum(e["dispatch"] is not None for e in events), "new_eps_requests": 0,
            "snapshot_status": "PARTIAL_SOURCE_FAILURE" if stopped else "VERIFIED_SELECTION_COMPLETE",
            "not_simultaneous_market_snapshot": True, "official_latest_or_all_revisions_proven": False,
            "generated_at": instant(), "production_eligible": False}
        put(root / "ACQUISITION_RESULT.json", result)
        files = {}
        for path in root.rglob("*"):
            if path.is_file() and path != root / ".scan.lock":
                body = path.read_bytes()
                files[path.relative_to(root).as_posix()] = {"bytes": len(body), "sha256": sha256(body)}
        manifest = {"artifact_kind": SNAPSHOT_KIND, "plan_id": plan["plan_id"], "plan_sha256": expected_plan_sha256,
            "files": files, "exact_runtime_exclusion": {"path": str(root / ".scan.lock"), "role": "OS_HELD_COORDINATION_ONLY", "content_hashed": False},
            "result_sha256": files["ACQUISITION_RESULT.json"]["sha256"], "snapshot_status": result["snapshot_status"]}
        put(root / "SNAPSHOT_MANIFEST.json", manifest)
    return sha256((root / "SNAPSHOT_MANIFEST.json").read_bytes()), result


def differences(old_rows, new_rows, market, period):
    old = {r["symbol"]: r for r in old_rows if (r["market"], r["period"]) == (market, period)}
    new = {r["symbol"]: r for r in new_rows}
    require(len(new) == len(new_rows), "REVENUE_NEW_DUPLICATE_OR_CONFLICT")
    result = []
    for symbol in sorted(set(old) | set(new)):
        before, after = old.get(symbol), new.get(symbol)
        status = "added" if before is None else "no_longer_observed" if after is None else "numeric_status_changed" if before["revenue_yoy_status"] != after["revenue_yoy_status"] else "value_changed" if before["revenue_yoy"] != after["revenue_yoy"] else "unchanged"
        result.append({"symbol": symbol, "market": market, "period": period, "comparison": status,
            "old": before, "new": after})
    return result


def replay_snapshot(root, expected_manifest_sha256, *, old_loader=None):
    old_loader = old_loader or load_delivery
    root = Path(root).resolve()
    raw = (root / "SNAPSHOT_MANIFEST.json").read_bytes()
    require(sha256(raw) == expected_manifest_sha256, "REVENUE_SNAPSHOT_MANIFEST_TAMPERED")
    manifest = read_metadata(raw)
    require(manifest["artifact_kind"] == SNAPSHOT_KIND and "request-plan.json" in manifest["files"] and
        "ACQUISITION_RESULT.json" in manifest["files"], "REVENUE_SNAPSHOT_MANIFEST_IDENTITY_INVALID")
    for name, expected in manifest["files"].items():
        path = (root / name).resolve()
        require(path.is_relative_to(root), "REVENUE_SNAPSHOT_PATH_ESCAPE")
        body = path.read_bytes()
        require(len(body) == expected["bytes"] and sha256(body) == expected["sha256"], "REVENUE_SNAPSHOT_SOURCE_TAMPERED")
    preliminary = read_metadata((root / "request-plan.json").read_bytes())
    features = old_loader(preliminary["old_feature_pin"])
    plan = read_plan(root, manifest["plan_sha256"], features)
    result = read_metadata((root / "ACQUISITION_RESULT.json").read_bytes())
    require(result["plan_id"] == manifest["plan_id"] == plan["plan_id"] and result["plan_sha256"] == manifest["plan_sha256"], "REVENUE_SNAPSHOT_PLAN_IDENTITY_MISMATCH")
    require(len(result["events"]) == len(plan["targets"]) == 6 and result["new_eps_requests"] == 0, "REVENUE_SNAPSHOT_BUDGET_OR_TARGETS_INVALID")
    selected, diff, sources, last_dispatch = [], [], [], None
    stopped = False
    for target, event in zip(plan["targets"], result["events"]):
        key = target_key(target)
        require((event["market"], event["period"], event["endpoint"]) == (target["market"], target["period"], target["endpoint"]), "REVENUE_SNAPSHOT_EVENT_TARGET_MISMATCH")
        require(event["event_sha256"] == hash_object({k: v for k, v in event.items() if k != "event_sha256"}) and
            event == read_metadata((root / "events" / (key + ".json")).read_bytes()), "REVENUE_SNAPSHOT_EVENT_TAMPERED")
        dispatch = event["dispatch"]
        if dispatch:
            require(not stopped and target["action"] == "REFRESH_ONCE", "REVENUE_DISPATCH_AFTER_STOP_OR_REUSE")
            intent = read_metadata((root / "intents" / (key + ".json")).read_bytes())
            request_id = hash_object({"plan_id": plan["plan_id"], "market": target["market"], "period": target["period"], "endpoint": target["endpoint"]})
            require(intent == {"plan_id": plan["plan_id"], "target": target, "request_identity": request_id,
                "dispatch": dispatch, "dispatch_sha256": hash_object(dispatch)} and dispatch["request_identity"] == request_id,
                "REVENUE_DISPATCH_BINDING_INVALID")
            require(dispatch["minimum_interval_seconds"] == 13 and dispatch["measurement_boundary"] == "CAPTURE_CALL_NOT_HTTP_WIRE_START", "REVENUE_DISPATCH_SCOPE_INVALID")
            require(dispatch["protocol"] == "FINMIND_CAPTURE_BOUNDARY_MONOTONIC_V1" and
                dispatch["clock_domain"] == "PROCESS_SESSION:" + dispatch["session_identity"] and
                _time(plan["created_at"]) <= _time(dispatch["utc_timestamp"]) <= _time(result["generated_at"]),
                "REVENUE_DISPATCH_SESSION_OR_UTC_INVALID")
            for value in (dispatch["monotonic_timestamp"], dispatch["actual_wait_seconds"]):
                require(type(value) in (int, float) and math.isfinite(value) and value >= 0, "REVENUE_DISPATCH_NUMERIC_INVALID")
            anchor = dispatch["previous_wait_anchor_monotonic"]
            require(type(anchor) in (int, float) and math.isfinite(anchor) and dispatch["monotonic_timestamp"] - anchor >= 13,
                "REVENUE_DISPATCH_INTERVAL_INVALID")
            require(dispatch["actual_wait_seconds"] <= dispatch["monotonic_timestamp"] - anchor, "REVENUE_WAIT_INCONSISTENT")
            if last_dispatch:
                require(dispatch["session_identity"] == last_dispatch["session_identity"] and dispatch["clock_domain"] == last_dispatch["clock_domain"] and
                    dispatch["previous_dispatch_interval_seconds"] == dispatch["monotonic_timestamp"] - last_dispatch["monotonic_timestamp"] and
                    dispatch["previous_dispatch_interval_seconds"] >= 13, "REVENUE_DISPATCH_SESSION_INVALID")
            last_dispatch = dispatch
        else:
            require(not (root / "intents" / (key + ".json")).exists(), "REVENUE_UNKNOWN_REQUEST_OUTCOME")
        old_rows = [r for r in features["core"]["inputs"]["revenue"] if (r["market"], r["period"]) == (target["market"], target["period"])]
        if event["source_status"] == "REFRESHED_VERIFIED":
            require(dispatch is not None, "REVENUE_REFRESH_WITHOUT_REQUEST")
            rows, outside = observations(root, event["receipt_reference"], plan, target, event["verified_at"])
            require(all(_time(r["observed_at"]) >= _time(dispatch["utc_timestamp"]) for r in rows), "REVENUE_OBSERVED_BEFORE_DISPATCH")
            require(outside == event["outside_universe_symbols"], "REVENUE_OUTSIDE_UNIVERSE_MISMATCH")
            selected.extend(rows)
            diff.extend(differences(old_rows, rows, target["market"], target["period"]))
        elif event["source_status"] == "REUSED_OLD_VERIFIED":
            require(dispatch is None and (stopped or target["action"] == "REUSE_VERIFIED_SUFFICIENT"), "REVENUE_SILENT_OLD_FALLBACK")
            selected.extend(old_rows)
        else:
            require(dispatch is not None and event["source_status"] == "FAILED_NEW_SNAPSHOT_NOT_SELECTED_NO_OLD_FALLBACK", "REVENUE_SNAPSHOT_UNKNOWN_STATUS")
            if event["receipt_reference"]:
                load_response(root, event["receipt_reference"])
            stopped = True
        sources.append({"market": target["market"], "period": target["period"], "status": event["source_status"],
            "selected_receipt": event["receipt_reference"] if event["source_status"] == "REFRESHED_VERIFIED" else
                target["old_source"] if event["source_status"] == "REUSED_OLD_VERIFIED" else None})
    require(result["new_revenue_requests"] == sum(e["dispatch"] is not None for e in result["events"]) <= 6,
        "REVENUE_SNAPSHOT_REQUEST_COUNT_MISMATCH")
    require(result["snapshot_status"] == manifest["snapshot_status"] == ("PARTIAL_SOURCE_FAILURE" if stopped else "VERIFIED_SELECTION_COMPLETE"), "REVENUE_SNAPSHOT_FALSE_PASS")
    inputs = deepcopy(features["core"]["inputs"])
    inputs["revenue"] = selected
    inputs["source_binding"] = {"input_mode": MODE, "snapshot_root": str(root), "snapshot_manifest_sha256": expected_manifest_sha256,
        "snapshot_plan_id": plan["plan_id"], "snapshot_plan_sha256": manifest["plan_sha256"],
        "parent_feature_pin": plan["old_feature_pin"], "parent_feature_content_sha256": features["content_sha256"],
        "snapshot_status": result["snapshot_status"], "coverage_root": features["core"]["inputs"]["source_binding"]["coverage_root"],
        "new_eps_requests": 0, "new_revenue_requests": result["new_revenue_requests"]}
    require(hash_object(inputs["eps"]) == plan["eps_input_sha256"] and hash_object(inputs["gaps"]) == plan["gap_input_sha256"], "REVENUE_EPS_OR_GAPS_CHANGED")
    return inputs, {"selection": sources, "differences": diff, "request_result": result}


def replay_snapshot_binding(binding):
    inputs, _ = replay_snapshot(binding["snapshot_root"], binding["snapshot_manifest_sha256"])
    require(inputs["source_binding"] == binding, "REVENUE_FEATURE_INPUT_BINDING_MISMATCH")
    return inputs

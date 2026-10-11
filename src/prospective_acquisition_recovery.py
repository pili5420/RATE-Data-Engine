"""Opt-in, offline resolution overlay. Original acquisition stores remain read-only."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import subprocess
import sys
from uuid import UUID

from .eps_duration_facts.model import require
from .eps_duration_facts.raw import sha256
from .full_market_history import put_bytes
from .provider_eps_candidate import _canonical, _time
from .provider_eps_metadata import read_metadata, number
from .provider_eps_dispatch import exclusive_scan, DispatchGate
from .provider_revenue_snapshot import endpoint
from .sources.mops_raw_evidence import NORMALIZATION_VERSION

KIND = "RATE_PROSPECTIVE_KNOWN_FAILURE_RESOLUTION_V1"
OUTCOME = "TERMINAL_FAILED_KNOWN_OUTCOME"
RECOVERED = "RECOVERED_FROM_KNOWN_TERMINAL_FAILURE"


def now():
    return datetime.now(timezone.utc).isoformat()


def offline_network_guard(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "urllib.Request"}:
        raise RuntimeError("RECOVERY_NETWORK_FORBIDDEN")


def read_pinned(ref):
    body = Path(ref["path"]).read_bytes()
    require(sha256(body) == ref["sha256"], "RECOVERY_EVIDENCE_TAMPER")
    return body


def object_at(ref):
    return read_metadata(read_pinned(ref))


def intent_identity(ident):
    require(isinstance(ident, str) and str(UUID(ident)) == ident, "RECOVERY_INTENT_ID_INVALID")


def load_binding(path, trusted_sha256):
    binding = object_at({"path": str(path), "sha256": trusted_sha256})
    require(binding["artifact_kind"] == "RATE_KNOWN_FAILURE_RECOVERY_BINDING_V1", "RECOVERY_BINDING_KIND")
    root = Path(binding["legacy_root"]).resolve()
    for relative, pin in binding["original_files"].items():
        file = (root / relative).resolve()
        require(file.is_relative_to(root), "RECOVERY_REFERENCE_ESCAPE")
        read_pinned({"path": str(file), "sha256": pin["sha256"]})
    require({str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and p != root / ".scan.lock"}
            == set(binding["original_files"]), "RECOVERY_ORIGINAL_STORE_CHANGED")
    config = object_at({"path": str(root / "CONFIG.json"), "sha256": binding["config_sha256"]})
    require(config["execution"] == binding["legacy_execution"] and
            config["authority_id"] == binding["authority_id"] and
            config["authority_sha256"] == binding["authority_sha256"] and
            Path(config["authority_root"]).resolve() == Path(binding["authority_root"]).resolve(), "RECOVERY_CONFIG_IDENTITY")
    checkout = Path(binding["legacy_checkout"]).resolve()
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=checkout).decode().strip()
    require(git("rev-parse", "HEAD") == config["execution"]["head_sha"] and
            git("merge-base", config["execution"]["base_sha"], "HEAD") == config["execution"]["base_sha"] and
            not git("status", "--porcelain"), "RECOVERY_LEGACY_EXECUTION_MISMATCH")
    engine_path = checkout / "scripts/run_prospective_provider_activation.py"
    require(sha256(engine_path.read_bytes()) == binding["legacy_pipeline_sha256"], "RECOVERY_ENGINE_TAMPER")
    spec = importlib.util.spec_from_file_location("pinned_original_acquisition_engine", engine_path)
    engine = importlib.util.module_from_spec(spec)
    # The original producer's record() retains its original physical __file__ identity.
    before = list(sys.path)
    try:
        spec.loader.exec_module(engine)
    finally:
        sys.path[:] = before
    auth = engine.load(binding["authority_root"], binding["authority_sha256"])
    require(auth["authority_id"] == binding["authority_id"], "RECOVERY_AUTHORITY_MISMATCH")
    return binding, config, auth, engine


def successful_prefix(binding, config, auth, engine, as_of):
    """Rebuild unchanged records with the pinned original producer and source validators."""
    root = Path(binding["legacy_root"])
    head, events, prior, receipts = None, [], {}, set()
    for index, path in enumerate(sorted((root / "events").iterdir())):
        body = path.read_bytes(); event = read_metadata(body); saved = event["record"]
        require(path.name == f"{index:08d}-" + sha256(body) + ".json" and
                event["previous_head"] == head and event["config_sha256"] == binding["config_sha256"], "RECOVERY_EVENT_TAMPER")
        ident = event["intent_id"]; intent_identity(ident)
        intent_bytes = (root / "intents" / (ident + ".json")).read_bytes(); intent = read_metadata(intent_bytes)
        require(sha256(intent_bytes) == event["intent_sha256"] and intent["intent_id"] == ident and
                intent["config_sha256"] == binding["config_sha256"] and intent["provider"] == saved["provider"] and
                intent["target"] == saved["target"] and intent["authority_id"] == auth["authority_id"] and
                _time(auth["activation_timestamp"]) <= _time(intent["requested_at"]) <= _time(saved["requested_at"]),
                "RECOVERY_SUCCESS_INTENT_INVALID")
        raw = (root / "raw" / (saved["raw_sha256"] + ".bin")).read_bytes()
        receipt = (root / "receipts" / (saved["receipt_sha256"] + ".json")).read_bytes()
        inspection = engine.inspect_source(saved["provider"], saved["target"], raw, receipt,
            saved["raw_sha256"], saved["receipt_sha256"], config["universe"], saved["validation_timestamp"])
        require(engine.record(inspection, auth, saved["first_seen_at"]) == saved and
                _time(saved["first_seen_at"]) <= _time(as_of) <= _time(now()) and
                (not events or _time(events[-1]["record"]["first_seen_at"]) <= _time(saved["first_seen_at"])),
                "RECOVERY_RECORD_REPLAY_MISMATCH")
        key = sha256(_canonical(saved["scope"]))
        require(event["previous_scope_observation"] == prior.get(key) and saved["receipt_sha256"] not in receipts,
                "RECOVERY_OBSERVATION_CHAIN_INVALID")
        prior[key] = saved["immutable_snapshot_id"]; receipts.add(saved["receipt_sha256"])
        events.append(event); head = sha256(body)
    require(head == binding["trusted_head_before_failure"], "RECOVERY_TRUSTED_HEAD_MISMATCH")
    return events


def failure_evidence(binding, ident, auth, events):
    intent_identity(ident)
    require(ident in binding["failures"] and ident not in {e["intent_id"] for e in events}, "RECOVERY_WRONG_INTENT")
    refs = binding["failures"][ident]
    required = {"intent", "raw", "receipt", "stop", "traceback", "request_start", "dispatch", "intent_binding", "checkpoint"}
    require(set(refs) == required, "RECOVERY_FAILURE_EVIDENCE_MISSING")
    bodies = {key: read_pinned(ref) for key, ref in refs.items()}
    values = {key: read_metadata(body) for key, body in bodies.items() if key not in {"raw", "traceback"}}
    intent, receipt, stop = values["intent"], values["receipt"], values["stop"]
    expected = {"market": "TPEX", "period": "2026-09"} if binding.get("acceptance_target") else intent["target"]
    require(intent["intent_id"] == ident and intent["provider"] == "MOPS Official" and intent["target"] == expected and
            intent["authority_id"] == auth["authority_id"] == binding["authority_id"] and
            intent["config_sha256"] == binding["config_sha256"], "RECOVERY_FAILURE_INTENT_MISMATCH")
    url = endpoint(intent["target"]["market"], intent["target"]["period"])
    status = receipt["http_status"]
    require(type(status) is int and 400 <= status <= 599 and (not binding.get("acceptance_target") or status == 502),
            "RECOVERY_NOT_PROVEN_HTTP_FAILURE")
    require(receipt["source_owner"] == "MOPS Official" and receipt["domain"] == "revenue" and
            receipt["acquisition_intent_id"] == ident and receipt["authority_id"] == auth["authority_id"] and
            receipt["market"] == intent["target"]["market"] and receipt["requested_period"] == intent["target"]["period"] and
            receipt["endpoint"] == receipt["final_url"] == url and url.startswith("https://") and
            receipt["fallback_used"] is False and receipt["request_method"] == "GET" and
            receipt["normalization_version"] == NORMALIZATION_VERSION and
            receipt["parser_sha256"] == sha256((Path(binding["legacy_checkout"]) / "src/sources/fundamental_history.py").read_bytes()) and
            receipt["body_sha256"] == sha256(bodies["raw"]) and receipt["response_bytes"] == len(bodies["raw"]),
            "RECOVERY_FAILURE_RESPONSE_MISMATCH")
    require(stop == {"intent_id": ident, "reason": "ACQUISITION_OR_VALIDATION_FAILED_NO_RETRY"}, "RECOVERY_STOP_MISMATCH")
    require(("MOPS_REVENUE_HTTP_" + str(status)).encode() in bodies["traceback"], "RECOVERY_TRACEBACK_MISMATCH")
    start, dispatch, side = values["request_start"], values["dispatch"], values["intent_binding"]
    dispatches = [object_at(ref) for ref in binding["dispatches"]]
    matching = [item for item in dispatches if item["intent_id"] == ident]
    require(len(matching) == 1 and matching[0] == dispatch, "RECOVERY_FAILED_INTENT_DISPATCH_COUNT")
    require(start["intent_id"] == dispatch["intent_id"] == side["intent_id"] == ident and
            start["authority_id"] == side["authority_id"] == auth["authority_id"] and
            start["target"] == side["target"] == dispatch["target"] == intent["target"] and
            side["original_intent_sha256"] == sha256(bodies["intent"]) and side["config_sha256"] == binding["config_sha256"] and
            side["dataset"] == start["dataset"] == "MOPS_MONTHLY_REVENUE_ARCHIVE" and
            dispatch["provider"] == side["provider"] == "MOPS Official" and
            dispatch["endpoint"] == url and start["request_started_at"] == receipt["request_started_at"] and
            side["dispatch_authorization"] == intent["dispatch"] == dispatch["dispatch"], "RECOVERY_DISPATCH_BINDING")
    d = intent["dispatch"]; stamp = number(d["monotonic_timestamp"])
    require(d["request_identity"] == ident and d["clock_domain"] == "PROCESS_SESSION:" + d["session_identity"] and
            d["measurement_boundary"] == "CAPTURE_CALL_NOT_HTTP_WIRE_START" and
            stamp - number(d["previous_wait_anchor_monotonic"]) >= number(d["minimum_interval_seconds"], minimum=13) and
            number(d["actual_wait_seconds"]) <= stamp - d["previous_wait_anchor_monotonic"], "RECOVERY_DISPATCH_INVALID")
    DispatchGate(d["minimum_interval_seconds"], clock=lambda: stamp, utc=now).check_outbound(d)
    require(_time(auth["activation_timestamp"]) <= _time(intent["requested_at"]) <= _time(receipt["request_started_at"]) <=
            _time(dispatch["observed_at"]) <= _time(receipt["retrieval_timestamp"]) <= _time(now()), "RECOVERY_FAILURE_TIME_INVALID")
    require(values["checkpoint"]["ledger_head"] == binding["trusted_head_before_failure"] and
            values["checkpoint"]["config_sha256"] == binding["config_sha256"], "RECOVERY_FAILURE_BOUNDARY")
    if events:
        require(_time(events[-1]["record"]["first_seen_at"]) <= _time(intent["requested_at"]), "RECOVERY_FAILURE_BOUNDARY_TIME")
    root = Path(binding["legacy_root"])
    require(Path(refs["intent"]["path"]).resolve() == (root / "intents" / (ident + ".json")).resolve(), "RECOVERY_INTENT_PATH")
    return {"intent_id": ident, "provider": intent["provider"], "target": intent["target"],
        "authority_id": auth["authority_id"], "config_sha256": binding["config_sha256"], "http_status": status,
        "endpoint": url, "request_started_at": receipt["request_started_at"], "received_at": receipt["retrieval_timestamp"],
        "failure_evidence_hashes": {key: sha256(body) for key, body in bodies.items()},
        "previous_trusted_head": binding["trusted_head_before_failure"], "classification": "KNOWN_TERMINAL_FAILURE"}


def create_resolution(root, binding_path, binding_pin, ident, resolved_at):
    binding, config, auth, engine = load_binding(binding_path, binding_pin)
    root = engine.external(root)
    legacy = Path(binding["legacy_root"]).resolve()
    require(not root.is_relative_to(legacy) and not legacy.is_relative_to(root), "RECOVERY_ORIGINAL_OUTPUT_FORBIDDEN")
    events = successful_prefix(binding, config, auth, engine, now())
    evidence = failure_evidence(binding, ident, auth, events)
    require(_time(evidence["received_at"]) <= _time(resolved_at) <= _time(now()), "RECOVERY_RESOLUTION_TIME_INVALID")
    core = {"artifact_kind": KIND, **evidence, "outcome": OUTCOME, "binding_sha256": binding_pin,
        "resolved_at": resolved_at, "resolution_semantics": "NO_RETRY_NO_SUCCESS_EVENT_NO_SOAK_CREDIT",
        "historical_pit": "UNPROVEN", "production_eligible": False, "first_refresh_allowed": False}
    resolution = {**core, "resolution_id": "known-failure-resolution-" + sha256(_canonical(core))}
    body = _canonical(resolution); pin = sha256(body)
    root.mkdir(parents=True, exist_ok=True)
    with exclusive_scan(root):
        require(not (root / "resolutions" / (ident + ".json")).exists() and
                not (root / "failures" / ident / "FAILURE.json").exists(), "RECOVERY_DUPLICATE_RESOLUTION")
        put_bytes(root, "failures/" + ident + "/FAILURE.json", _canonical(evidence))
        put_bytes(root, "objects/" + pin + ".json", body)
        put_bytes(root, "resolutions/" + ident + ".json", body)
    return pin


def replay_recovered(root, binding_path, binding_pin, trusted_resolutions, as_of):
    binding, config, auth, engine = load_binding(binding_path, binding_pin)
    events = successful_prefix(binding, config, auth, engine, as_of)
    legacy = Path(binding["legacy_root"]); root = Path(root)
    completed = {e["intent_id"] for e in events}
    intents = {p.stem for p in (legacy / "intents").iterdir()}
    unresolved = intents - completed
    require(unresolved == set(trusted_resolutions), "ACTIVATION_UNKNOWN_REQUEST_OUTCOME_NO_RETRY")
    require({p.stem for p in (root / "resolutions").glob("*.json")} == unresolved, "RECOVERY_RESOLUTION_SET_MISMATCH")
    resolutions = []
    for ident, pin in trusted_resolutions.items():
        body = read_pinned({"path": str(root / "resolutions" / (ident + ".json")), "sha256": pin})
        require((root / "objects" / (pin + ".json")).read_bytes() == body, "RECOVERY_OBJECT_TAMPER")
        resolution = read_metadata(body)
        evidence = failure_evidence(binding, ident, auth, events)
        require(read_metadata((root / "failures" / ident / "FAILURE.json").read_bytes()) == evidence, "RECOVERY_FAILURE_INDEX_TAMPER")
        expected = {"artifact_kind": KIND, **evidence, "outcome": OUTCOME, "binding_sha256": binding_pin,
            "resolved_at": resolution["resolved_at"], "resolution_semantics": "NO_RETRY_NO_SUCCESS_EVENT_NO_SOAK_CREDIT",
            "historical_pit": "UNPROVEN", "production_eligible": False, "first_refresh_allowed": False}
        require(resolution == {**expected, "resolution_id": "known-failure-resolution-" + sha256(_canonical(expected))} and
                _time(evidence["received_at"]) <= _time(resolution["resolved_at"]) <= _time(as_of) <= _time(now()),
                "RECOVERY_RESOLUTION_INVALID")
        resolutions.append(resolution)
    if (legacy / "STOP.json").exists():
        stop = read_metadata((legacy / "STOP.json").read_bytes())
        require(stop["intent_id"] in trusted_resolutions and
                Path(binding["failures"][stop["intent_id"]]["stop"]["path"]).resolve() == (legacy / "STOP.json").resolve(),
                "ACTIVATION_PERSISTED_STOP")
    require(resolutions, "RECOVERY_TERMINAL_RESOLUTION_REQUIRED")
    return {"runtime_status": RECOVERED, "successful_prefix": len(events),
        "trusted_ledger_head": binding["trusted_head_before_failure"], "authority_id": auth["authority_id"],
        "resolutions": resolutions, "observation_chains_verified": True, "full_soak_pass": False,
        "network_requests": 0, "financial_requests": 0, "retry_allowed": False,
        "new_acquisition_authorized": False, "production_eligible": False, "historical_pit": "UNPROVEN"}


def assert_fresh_intent(binding, ident):
    intent_identity(ident)
    require(not (Path(binding["legacy_root"]) / "intents" / (ident + ".json")).exists() and
            ident not in binding["failures"], "RECOVERY_FAILED_INTENT_REUSE_FORBIDDEN")
    return {"intent_id": ident, "dispatch_authorized": False, "control_center_authorization_required": True}

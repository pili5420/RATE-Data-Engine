"""Opt-in evidence pipeline. No scheduler, scoring, publication or state writes."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import argparse
import importlib.util
import sys
import traceback
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.eps_duration_facts.model import require
from src.eps_duration_facts.raw import sha256
from src.full_market_history import put_bytes
from src.provider_eps_candidate import API, _canonical, _time
from src.provider_eps_dispatch import exclusive_scan
from src.provider_eps_metadata import read_metadata
from src.provider_financial_features import within_git_checkout
from src.prospective_fundamental_provider import inspect_source, prospective_record, issuer_readiness
from src.prospective_provider_activation import CONTRACT, load, seal, git
from src.provider_revenue_snapshot import endpoint, strict_opener
from src.sources.fundamental_history import MOPSHistoricalFundamentalAdapter


def now():
    return datetime.now(timezone.utc).isoformat()


def external(root):
    root = Path(root).absolute()
    require(not within_git_checkout(root) and not any(p.casefold() in {"production", "latest", "state",
        "portfolio", "ledger", "artifacts", "snapshots", "data"} for p in root.parts), "ACTIVATION_PROTECTED_OUTPUT")
    require(not any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()) for p in (root, *root.parents)),
        "ACTIVATION_LINKED_OUTPUT")
    return root.resolve()


def create(root, authority_root, authority_sha256, universe, execution):
    root = external(root)
    require(not root.exists(), "ACTIVATION_NEW_STORE_REQUIRED")
    auth = load(authority_root, authority_sha256)
    from collections import Counter
    require(universe["verification_status"] == "PASS" and len({s["symbol"] for s in universe["stocks"]}) == 1978 and
        Counter(s["market"] for s in universe["stocks"]) == {"TWSE": 1085, "TPEX": 893}, "ACTIVATION_UNIVERSE_INVALID")
    require(set(execution) == {"base_sha", "head_sha"} and all(isinstance(v, str) and len(v) == 40 and
        set(v) <= set("0123456789abcdef") for v in execution.values()), "ACTIVATION_EXECUTION_INVALID")
    check_execution(execution)
    config = {"contract": CONTRACT, "authority_root": str(Path(authority_root).resolve()), "authority_sha256": authority_sha256,
        "authority_id": auth["authority_id"], "universe": universe, "execution": execution}
    root.mkdir(parents=True)
    put_bytes(root, "CONFIG.json", _canonical(config))
    for name in ("events", "intents", "captures"):
        (root / name).mkdir()
    return sha256((root / "CONFIG.json").read_bytes())


def check_execution(execution):
    require(git("rev-parse", "HEAD").decode().strip() == execution["head_sha"] and
        git("merge-base", execution["base_sha"], execution["head_sha"]).decode().strip() == execution["base_sha"] and
        not git("status", "--porcelain").strip(), "ACTIVATION_EXACT_HEAD_OR_WORKTREE_MISMATCH")


def record(inspection, authority, first_seen_at):
    # Reuse the accepted financial/time validation without changing its historical artifact.
    candidate = prospective_record(inspection, authority["activation_timestamp"], first_seen_at)
    core = {k: deepcopy(v) for k, v in candidate.items() if k not in
        {"immutable_snapshot_id", "candidate_activation_timestamp", "provider_authorization", "sandbox_only"}}
    core.update(activation_timestamp=authority["activation_timestamp"], authority_id=authority["authority_id"],
        provider_authorization="AUTHORIZED_PROSPECTIVE_ONLY", prospective_evidence_credit=True,
        acquisition_pipeline_identity={"path":"scripts/run_prospective_provider_activation.py",
            "sha256":sha256(Path(__file__).read_bytes()),"contract_sha256":sha256(_canonical(CONTRACT))})
    return {**core, "immutable_snapshot_id": "authorized-prospective-acquisition-" + sha256(_canonical(core))}


def replay(root, config_sha256, trusted_head, as_of):
    root = external(root)
    config_bytes = (root / "CONFIG.json").read_bytes()
    require(sha256(config_bytes) == config_sha256, "ACTIVATION_CONFIG_TAMPER")
    config = read_metadata(config_bytes)
    require(config["contract"] == CONTRACT, "ACTIVATION_CONTRACT_TAMPER")
    check_execution(config["execution"])
    auth = load(config["authority_root"], config["authority_sha256"])
    require(auth["authority_id"] == config["authority_id"], "ACTIVATION_AUTHORITY_MISMATCH")
    events, head, prior, completed = [], None, {}, set()
    for index, path in enumerate(sorted((root / "events").iterdir())):
        body = path.read_bytes(); event = read_metadata(body); saved = event["record"]
        require(path.name == f"{index:08d}-" + sha256(body) + ".json" and event["previous_head"] == head and
            event["config_sha256"] == config_sha256, "ACTIVATION_EVENT_TAMPER")
        ident = event["intent_id"]
        intent_bytes = (root / "intents" / (ident + ".json")).read_bytes(); intent = read_metadata(intent_bytes)
        require(sha256(intent_bytes) == event["intent_sha256"] and intent["intent_id"] == ident and
            intent["config_sha256"] == config_sha256 and intent["provider"] == saved["provider"] and
            intent["target"] == saved["target"] and intent["authority_id"] == auth["authority_id"] and
            _time(auth["activation_timestamp"]) <= _time(intent["requested_at"]) <= _time(saved["requested_at"]),
            "ACTIVATION_INTENT_MISMATCH")
        raw = (root / "raw" / (saved["raw_sha256"] + ".bin")).read_bytes()
        receipt = (root / "receipts" / (saved["receipt_sha256"] + ".json")).read_bytes()
        inspection = inspect_source(saved["provider"], saved["target"], raw, receipt, saved["raw_sha256"],
            saved["receipt_sha256"], config["universe"], saved["validation_timestamp"])
        require(record(inspection, auth, saved["first_seen_at"]) == saved and
            _time(saved["first_seen_at"]) <= _time(as_of) <= _time(now()) and
            (not events or _time(events[-1]["record"]["first_seen_at"]) <= _time(saved["first_seen_at"])),
            "ACTIVATION_RECORD_REPLAY_MISMATCH")
        scope = sha256(_canonical(saved["scope"]))
        require(event["previous_scope_observation"] == prior.get(scope) and
            saved["receipt_sha256"] not in {e["record"]["receipt_sha256"] for e in events}, "ACTIVATION_OBSERVATION_CHAIN_INVALID")
        prior[scope] = saved["immutable_snapshot_id"]; completed.add(ident); events.append(event); head = sha256(body)
    require(head == trusted_head, "ACTIVATION_TRUSTED_HEAD_MISMATCH")
    unresolved = {p.stem for p in (root / "intents").iterdir()} - completed
    require(not unresolved, "ACTIVATION_UNKNOWN_REQUEST_OUTCOME_NO_RETRY")
    require(not (root / "STOP.json").exists(), "ACTIVATION_PERSISTED_STOP")
    return config, auth, events


def acquire_once(root, config_sha256, trusted_head, provider, target, capture, *, gate, clock=now):
    """Capture is the pinned existing transport, not a second collector. No import mode."""
    root = external(root)
    with exclusive_scan(root):
        config, auth, events = replay(root, config_sha256, trusted_head, clock())
        require(provider in CONTRACT["providers"], "ACTIVATION_PROVIDER_MISMATCH")
        markets = {s["symbol"]: s["market"] for s in config["universe"]["stocks"]}
        if provider == "FinMind":
            require(set(target) == {"symbol", "market"} and markets.get(target["symbol"]) == target["market"], "ACTIVATION_TARGET_INVALID")
        else:
            require(set(target) == {"market", "period"}, "ACTIVATION_TARGET_INVALID")
            endpoint(target["market"], target["period"])
        require(_time(auth["activation_timestamp"]) <= _time(clock()) <= _time(now()), "ACTIVATION_REQUEST_BEFORE_AUTHORIZATION")
        ident = str(uuid4())
        dispatch = gate.boundary(ident)
        requested = clock()
        require(_time(auth["activation_timestamp"]) <= _time(requested) <= _time(now()), "ACTIVATION_REQUEST_TIME_INVALID")
        require(not events or _time(events[-1]["record"]["first_seen_at"]) <= _time(requested), "ACTIVATION_CLOCK_REGRESSED")
        intent = {"intent_id": ident, "authority_id": auth["authority_id"], "config_sha256": config_sha256,
            "provider": provider, "target": target, "requested_at": requested, "dispatch": dispatch}
        intent_bytes = _canonical(intent)
        put_bytes(root, "intents/" + ident + ".json", intent_bytes)
        directory = root / "captures" / ident
        directory.mkdir(); (directory / "raw").mkdir(); (directory / "receipts").mkdir()
        try:
            gate.check_outbound(dispatch)
            raw, receipt = capture(directory, intent)
            put_bytes(directory, "captured-response.bin", raw)
            put_bytes(directory, "captured-receipt.json", receipt)
            validated = clock()
            inspection = inspect_source(provider, target, raw, receipt, sha256(raw), sha256(receipt), config["universe"], validated)
            require(inspection["receipt_sha256"] not in {e["record"]["receipt_sha256"] for e in events}, "ACTIVATION_DUPLICATE_OBSERVATION")
            require(inspection["requested_at"] is not None, "PROSPECTIVE_REQUEST_TIME_NOT_EVIDENCED")
            require(_time(requested) <= _time(inspection["requested_at"]), "ACTIVATION_LEGACY_ACQUISITION_REJECTED")
            saved = record(inspection, auth, clock())
            prior = next((e["record"]["immutable_snapshot_id"] for e in reversed(events) if e["record"]["scope"] == saved["scope"]), None)
            require(saved["receipt_sha256"] not in {e["record"]["receipt_sha256"] for e in events}, "ACTIVATION_DUPLICATE_OBSERVATION")
            event = {"config_sha256": config_sha256, "previous_head": trusted_head, "previous_scope_observation": prior,
                "intent_id": ident, "intent_sha256": sha256(intent_bytes), "record": saved,
                "version_semantics": "LOCAL_OBSERVATION_ORDER_NOT_OFFICIAL_REVISION_ORDER"}
            body = _canonical(event)
            put_bytes(root, "raw/" + sha256(raw) + ".bin", raw)
            put_bytes(root, "receipts/" + sha256(receipt) + ".json", receipt)
            put_bytes(root, f"events/{len(events):08d}-" + sha256(body) + ".json", body)
            return sha256(body)
        except Exception:
            put_bytes(root, "STOP.json", _canonical({"intent_id": ident, "reason": "ACQUISITION_OR_VALIDATION_FAILED_NO_RETRY"}))
            put_bytes(root, "traceback.txt", traceback.format_exc().encode())
            raise
        finally:
            gate.completed()


def finmind_capture(transport_path, transport_sha256, *, token=None):
    path = Path(transport_path)
    require(sha256(path.read_bytes()) == transport_sha256, "ACTIVATION_TRANSPORT_TAMPER")
    spec = importlib.util.spec_from_file_location("authorized_existing_finmind_transport", path)
    transport = importlib.util.module_from_spec(spec); spec.loader.exec_module(transport)
    def capture(directory, intent):
        transport.capture(directory, intent["intent_id"], API, intent["target"]["symbol"],
            start="2024-07-01", end="2026-06-30", token=token)
        receipt = (directory / "receipts" / (intent["intent_id"] + ".json")).read_bytes()
        value = read_metadata(receipt)
        require(value.get("raw_capture_status") == "COMPLETE", "ACTIVATION_CAPTURE_NOT_COMPLETE")
        path = (directory / value["raw_path"]).resolve()
        require(path.is_relative_to(directory.resolve()), "ACTIVATION_CAPTURE_PATH_ESCAPE")
        return path.read_bytes(), receipt
    return capture


def mops_capture(*, opener=None, clock=now):
    def capture(directory, intent):
        adapter = MOPSHistoricalFundamentalAdapter(warmup_evidence_root=directory, min_interval_seconds=0,
            evidence_context={"acquisition_intent_id": intent["intent_id"], "authority_id": intent["authority_id"]})
        calls = []
        def open_once(request, timeout=45):
            require(not calls, "ACTIVATION_NO_RETRY")
            require(request.full_url == endpoint(intent["target"]["market"], intent["target"]["period"]), "ACTIVATION_ENDPOINT_MISMATCH")
            calls.append(True)
            # This hook precedes the actual existing opener; never derive it from retrieval.
            started = clock()
            require(_time(intent["requested_at"]) <= _time(started), "ACTIVATION_REQUEST_TIME_INVALID")
            adapter.evidence_context["request_started_at"] = started
            return (opener or strict_opener())(request, timeout=timeout)
        adapter.opener = open_once
        adapter.fetch_revenue_period(intent["target"]["market"], intent["target"]["period"])
        require(len(calls) == len(adapter.diagnostics) == 1, "ACTIVATION_EXACTLY_ONE_REQUEST_REQUIRED")
        ref = adapter.diagnostics[0]["raw_response_reference"]
        receipt = (directory / ref["path"]).read_bytes(); r = read_metadata(receipt)
        return (directory / r["raw_path"]).read_bytes(), receipt
    return capture


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--operation", choices=("seal", "create", "acquire", "replay"), default="replay")
    p.add_argument("--binding", type=Path); p.add_argument("--binding-sha256")
    p.add_argument("--replay-root", type=Path)
    p.add_argument("--config-sha256"); p.add_argument("--trusted-head"); p.add_argument("--as-of")
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    if args.operation != "replay":
        require(args.binding is not None and args.binding_sha256, "ACTIVATION_EXTERNAL_BINDING_REQUIRED")
        body = args.binding.read_bytes()
        require(sha256(body) == args.binding_sha256, "ACTIVATION_EXTERNAL_BINDING_TAMPER")
        binding = read_metadata(body)
        check_execution(binding["execution"])
        output = external(args.output)
        if args.operation == "seal":
            proof, receipt = Path(binding["proof_path"]).read_bytes(), Path(binding["proof_receipt_path"]).read_bytes()
            pin = seal(output, proof, binding["proof_sha256"], receipt, binding["proof_receipt_sha256"], binding["main_sha"], now())
            print("activation_authority_sha256=" + pin)
        elif args.operation == "create":
            universe_bytes = Path(binding["universe_path"]).read_bytes()
            require(sha256(universe_bytes) == binding["universe_sha256"], "ACTIVATION_UNIVERSE_PIN_MISMATCH")
            from src.provider_eps_coverage import load_universe
            universe = load_universe(binding["universe_path"], binding["universe_sha256"], binding["universe_commit"])
            pin = create(output, binding["authority_root"], binding["authority_sha256"], universe, binding["execution"])
            print("config_sha256=" + pin)
        else:
            from src.provider_eps_dispatch import DispatchGate
            gate = DispatchGate(13, prior_dispatch=True, utc=now)
            provider = binding["provider"]
            if provider == "FinMind":
                import os
                capture = finmind_capture(binding["transport_path"], binding["transport_sha256"], token=os.environ.get("FINMIND_TOKEN"))
            else:
                require(provider == "MOPS Official", "ACTIVATION_PROVIDER_MISMATCH")
                capture = mops_capture()
            require(output == Path(binding["evidence_root"]).resolve(), "ACTIVATION_OUTPUT_BINDING_MISMATCH")
            head = acquire_once(output, binding["config_sha256"], binding["trusted_head"], provider, binding["target"], capture, gate=gate)
            print("ledger_head=" + head)
        return 0
    require(args.replay_root is not None and args.config_sha256 and args.as_of, "ACTIVATION_REPLAY_BINDING_REQUIRED")
    config, auth, events = replay(args.replay_root, args.config_sha256, args.trusted_head, args.as_of)
    output = external(args.output)
    require(not output.exists(), "ACTIVATION_NO_OUTPUT_OVERWRITE")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(_canonical({"authority_id": auth["authority_id"], "ledger_head": args.trusted_head,
        "events": len(events), "issuer_readiness": issuer_readiness(config, events), "historical_pit": "UNPROVEN",
        "production_eligible": False, "first_refresh_allowed": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

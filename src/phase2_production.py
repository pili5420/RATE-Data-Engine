"""Phase 2 orchestration over canonical persisted state and frozen rule owners."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from .cer074_acceptance import atomic_write_json, sha256, strip_runtime
from .full_market_catalogue import approved_policy, policy_hash, validate_catalogue
from .full_market_rotation import (CONTINUITY, EXTERNAL_FEED, UNIVERSE, bind_full_universe,
                                   evaluate_rotation, rank_full_market)
from .production_live_state import (ARTIFACTS, CADENCE_DIR, STATE_NAME, load_live_state, require,
                                    validate_material)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "config/RATE_FULL_MARKET_ROTATION_CONTRACT_V1.json"
SOURCE_SCHEMA = "RATE-FULL-MARKET-PRODUCTION-SOURCE-BUNDLE-V1"
_DERIVED_RESULTS = {}


def contract():
    value = json.loads(CONTRACT_PATH.read_bytes())
    require(value.get("eligibility_policy_sha256") == policy_hash(), "PHASE2_POLICY_HASH_MISMATCH")
    return value


def require_intraday_authority():
    registry = json.loads((ROOT / "config/RATE_EXTERNAL_PRODUCTION_DEPENDENCIES.json").read_bytes())
    matches = [item for item in registry["dependencies"] if item.get("dependency_id") == EXTERNAL_FEED]
    require(len(matches) == 1 and matches[0].get("status") == "PASS"
            and matches[0].get("fallback_allowed") is False, EXTERNAL_FEED)


def canonical_slots(state_root):
    root = Path(state_root) / "live"
    for path in sorted(root.glob("*/*")):
        if not path.is_dir():
            continue
        cadence = next((c for c, directory in CADENCE_DIR.items() if path.name == directory), None)
        require(cadence is not None, "CANONICAL_SLOT_INVALID")
        yield path.parent.name, cadence


def latest_predecessor(state_root, trading_date, cadence):
    slots = [(day, time) for day, time in canonical_slots(state_root)
             if (day, time) < (trading_date, cadence)
             and (cadence != "07:30" or time == "19:30" and day < trading_date)]
    require(slots, "LIVE_PREVIOUS_PRODUCTION_STATE_MISSING")
    day, time = max(slots)
    if cadence == "07:30":
        from scripts.resolve_production_runtime_context import _previous_legal_trading_day
        require(day == _previous_legal_trading_day(trading_date), "LATEST_PASS_1930_STATE_REQUIRED")
    if cadence in {"09:30", "12:00"}:
        require((day, time) == (trading_date, "07:30" if cadence == "09:30" else "09:30"),
                "INCREMENTAL_PREVIOUS_SLOT_INVALID")
    loaded = load_live_state(state_root, day, time)
    return day, time, loaded


def validate_first_refresh(previous, state_root, trading_date, cadence):
    authority = approved_policy()["first_refresh"]
    require(cadence == authority["cadence"], "FIRST_REFRESH_CADENCE_INVALID")
    require(previous.get("current_state_id") == authority["predecessor_state_id"]
            and previous.get("decision_payload_hash") == authority["predecessor_state_hash"],
            "FIRST_REFRESH_PREDECESSOR_BINDING_INVALID")
    require(not any(previous["decision"].get(key) for key in ("top50", "short_top30", "long_top30", "records")),
            "FIRST_REFRESH_PREDECESSOR_NOT_RANKLESS")
    for day, time in canonical_slots(state_root):
        state = load_live_state(state_root, day, time)["state"]
        if (state["decision"].get("first_full_market_refresh_authority") or {}).get("consumed") is True:
            raise RuntimeError("FIRST_FULL_MARKET_REFRESH_AUTHORITY_ALREADY_CONSUMED")
    day, time, latest = latest_predecessor(state_root, trading_date, cadence)
    require(latest["state"]["current_state_id"] == previous["current_state_id"], "FIRST_REFRESH_PREDECESSOR_NOT_LATEST")
    require((day, time) == (authority["predecessor_trading_date"], authority["predecessor_cadence"]),
            "FIRST_REFRESH_PREDECESSOR_BINDING_INVALID")
    return True


def resolve_phase2_context(*, cadence, event_name, dispatch_trading_date, state_root):
    from scripts.resolve_production_runtime_context import _today_taipei
    from .cer080_multi_day_continuity import is_trading_day, TRADING_CALENDAR_SOURCE
    trading_date = _today_taipei() if event_name != "workflow_dispatch" else dispatch_trading_date
    require(trading_date, "WORKFLOW_DISPATCH_REQUIRES_EXPLICIT_TRADING_DATE")
    mode = "VALIDATION_ONLY" if event_name not in {"schedule", "workflow_dispatch"} else (
        "RUN" if is_trading_day(trading_date) else "NOOP_NON_TRADING_DAY")
    out = {"artifact": "RATE_PRODUCTION_RUNTIME_CONTEXT", "validation_status": "PASS",
           "event_name": event_name, "cadence": cadence, "trading_date": trading_date,
           "trading_date_resolution": "DYNAMIC_TAIWAN_TRADING_DATE" if event_name == "schedule" else "EXPLICIT_WORKFLOW_DISPATCH_INPUT",
           "runtime_mode": mode, "calendar": {"trading_calendar_source": TRADING_CALENDAR_SOURCE},
           "previous_trading_date": "", "previous_cadence": "", "previous_state_evidence_path": "",
           "phase2": True, "fallback_used": False, "production_persistent_state_reset_count": 0}
    if mode == "RUN":
        day, time, previous = latest_predecessor(state_root, trading_date, cadence)
        out.update(previous_trading_date=day, previous_cadence=time,
                   previous_state_id=previous["state"]["current_state_id"],
                   previous_state_hash=previous["state"]["decision_payload_hash"],
                   previous_state_evidence_path=str(previous["path"]))
    return out


def continue_accounts(previous):
    decision = previous["decision"]
    accounts = {key: copy.deepcopy(decision[key]) for key in ("roy_portfolio", "ai_paper_portfolio", "transaction_ledger")}
    ledger = accounts["transaction_ledger"]
    if "transactions" not in ledger:
        require(previous["current_state_id"] == approved_policy()["first_refresh"]["predecessor_state_id"]
                and ledger.get("ledger_continuity_mode") == "POST_REBASELINE_ONLY", "LEDGER_CONTINUITY_INVALID")
        # The approved opening boundary has no recoverable pre-boundary transactions.
        # An empty post-boundary list does not fabricate an opening transaction.
        ledger["transactions"] = []
    require(isinstance(ledger["transactions"], list) and not ledger.get("reset"), "LEDGER_CONTINUITY_INVALID")
    return accounts


def validate_account_continuity(previous, decision):
    expected = continue_accounts(previous)
    require(decision.get("roy_portfolio") == expected["roy_portfolio"], "ROY_PORTFOLIO_CONTINUITY_FAILED")
    require(decision.get("ai_paper_portfolio") == expected["ai_paper_portfolio"], "AI_PORTFOLIO_CONTINUITY_FAILED")
    require(decision.get("transaction_ledger") == expected["transaction_ledger"], "TRANSACTION_LEDGER_CONTINUITY_FAILED")
    return True


def decision_from_evaluation(result, previous, *, catalogue, trading_date, cadence, source_bundle_hash):
    require(result.get("validation_status") == "PASS" and result.get("ranking"), "PHASE2_EVALUATION_NOT_PASS")
    ranking = result["ranking"]
    require(all(len(ranking[key]) == count for key, count in (("top50", 50), ("short_top30", 30), ("long_top30", 30))),
            "PHASE2_RANKING_INCOMPLETE")
    decision = {"schema_version": "RATE-PHASE2-PRODUCTION-DECISION-STATE-V1", "phase2": True,
                "execution_scope": "PRODUCTION", "trading_date": trading_date, "cadence": cadence,
                "previous_state_resolution": "PERSISTED_PRODUCTION_STATE", "previous_state_id": previous["current_state_id"],
                "previous_state_hash": previous["decision_payload_hash"], "previous_trading_date": previous["decision"]["trading_date"],
                "previous_cadence": previous["decision"]["cadence"], "source_bundle_hash": source_bundle_hash,
                "input_snapshot_id": result["input_snapshot_id"], "production_snapshot_id": result["production_snapshot_id"],
                "previous_production_snapshot_id": previous_snapshot(previous),
                "candidate_universe_source": UNIVERSE, "ranking_refresh_source": "FULL_MARKET_SCAN",
                "continuity_baseline_source": result["continuity_baseline_source"],
                "ranking_turnover_status": result.get("ranking_turnover_status", "PRESERVED_INCREMENTAL"),
                "runtime_mode": result["mode"], "full_market_refresh": result["full_market_refresh"],
                "ranking_trading_date": trading_date if cadence == "19:30" else previous["decision"]["ranking_trading_date"],
                "catalogue": copy.deepcopy(catalogue), "records": copy.deepcopy(ranking.get("records", previous["decision"].get("records"))),
                **{key: copy.deepcopy(ranking[key]) for key in ("top50", "short_top30", "long_top30")},
                **continue_accounts(previous), "fallback_used": False, "validation_status": "PASS"}
    if result["continuity_baseline_source"] == "FIRST_FULL_MARKET_REFRESH_AUTHORITY":
        authority = approved_policy()["first_refresh"]
        decision["first_full_market_refresh_authority"] = {**authority, "consumed": True, "completed": True,
                                                           "policy_id": approved_policy()["policy_id"], "policy_hash": policy_hash()}
    else:
        receipt = previous["decision"].get("first_full_market_refresh_authority")
        if receipt:
            decision["first_full_market_refresh_authority"] = copy.deepcopy(receipt)
    validate_account_continuity(previous, decision)
    digest = sha256(strip_runtime(decision))
    return {"current_state_id": "rate-state-" + digest[:24], "decision_payload_hash": digest,
            "previous_state_id": previous["current_state_id"], "decision": decision}


def validate_transition(previous, state, *, state_root, trading_date, cadence):
    decision = state["decision"]
    require(decision.get("phase2") is True and decision.get("fallback_used") is False
            and decision.get("validation_status") == "PASS", "PHASE2_DECISION_INVALID")
    require(decision.get("previous_state_id") == previous["current_state_id"]
            and decision.get("previous_state_hash") == previous["decision_payload_hash"], "LIVE_STATE_LINEAGE_INVALID")
    require(decision.get("trading_date") == trading_date and decision.get("cadence") == cadence,
            "PHASE2_DECISION_SLOT_INVALID")
    latest = latest_predecessor(state_root, trading_date, cadence)[2]["state"]
    require(latest["current_state_id"] == previous["current_state_id"], "PHASE2_PREDECESSOR_NOT_LATEST")
    validate_account_continuity(previous, decision)
    if decision.get("continuity_baseline_source") == "FIRST_FULL_MARKET_REFRESH_AUTHORITY":
        validate_first_refresh(previous, state_root, trading_date, cadence)
        receipt = decision.get("first_full_market_refresh_authority") or {}
        expected = {**approved_policy()["first_refresh"], "consumed": True, "completed": True,
                    "policy_id": approved_policy()["policy_id"], "policy_hash": policy_hash()}
        require(receipt == expected and decision.get("ranking_turnover_status") == expected["ranking_turnover_status"],
                "FIRST_REFRESH_AUTHORITY_BINDING_INVALID")
    else:
        require(decision.get("continuity_baseline_source") == CONTINUITY
                and len(previous["decision"].get("short_top30", [])) == 30, "PREVIOUS_RANKED_CONTINUITY_REQUIRED")
        require(decision.get("first_full_market_refresh_authority") == previous["decision"].get("first_full_market_refresh_authority"),
                "FIRST_REFRESH_AUTHORITY_RECEIPT_LOST")
    ranking = rank_full_market(decision["records"])
    require(all(decision[key] == ranking[key] for key in ("top50", "short_top30", "long_top30")), "PHASE2_RANKING_BINDING_INVALID")
    ranking_date = decision["ranking_trading_date"]
    validate_catalogue(decision["catalogue"], ranking_date)
    symbols, _ = bind_full_universe(decision["catalogue"], contract(), ranking_date, [])
    require({row["symbol"] for row in decision["records"]} == set(symbols)
            and len(decision["records"]) == len(symbols), "FULL_MARKET_INPUTS_INCOMPLETE")
    if cadence != "19:30":
        require(all(decision[key] == previous["decision"][key] for key in ("records", "top50", "short_top30", "long_top30")),
                "INCREMENTAL_RANKING_CHANGE_FORBIDDEN")
    return True


def persist_prepared_state(state, runtime_root, cadence):
    decision = state["decision"]
    entry = {key: decision[key] for key in ("trading_date", "cadence", "execution_scope", "previous_state_resolution", "previous_state_id")}
    entry.update(current_state_id=state["current_state_id"], decision_payload_hash=state["decision_payload_hash"])
    persist = {"artifact": ARTIFACTS[cadence], "validation_status": "PASS", "current_state_id": state["current_state_id"],
               "current_state_hash": state["decision_payload_hash"], "previous_state_id": state["previous_state_id"],
               "persist_result": {"status": "PERSISTED", "state_entry": entry}}
    material = {"state_entry": entry, "decision_state": state}
    validate_material(persist, material, decision["trading_date"], cadence)
    path = Path(runtime_root) / "decision_state" / CADENCE_DIR[cadence] / (state["current_state_id"] + ".json")
    if path.exists():
        require(json.loads(path.read_bytes()) == material, "PRODUCTION_STATE_IDEMPOTENCY_CONFLICT")
    else:
        atomic_write_json(path, material)
    return persist


def validate_phase2_source_bundle(bundle, *, trading_date, cadence):
    from scripts.publish_production_source_bundle_latest import validate_freshness
    try:
        require(bundle.get("schema_version") == SOURCE_SCHEMA and bundle.get("validation_status") == "PASS"
                and bundle.get("source_status") == bundle.get("freshness_status") == "PASS"
                and bundle.get("fallback_used") is False and bundle.get("blocked_dependencies") == []
                and bundle.get("datasets_missing") == [], "PHASE2_SOURCE_BUNDLE_NOT_PASS")
        require(bundle.get("trading_date") == trading_date and bundle.get("cadence") == cadence,
                "PHASE2_SOURCE_BINDING_INVALID")
        require(bundle.get("production_snapshot_id") and bundle.get("input_snapshot_id"), "PHASE2_SNAPSHOT_BINDING_MISSING")
        material = bundle["input_material"]
        require(material.get("artifact") == ("RATE_FULL_MARKET_EOD_INPUTS" if cadence == "19:30" else "RATE_PHASE2_CARRIED_INPUTS")
                and material.get("evidence_scope") == "PRODUCTION"
                and material.get("trading_date") == trading_date and material.get("cadence") == cadence
                and material.get("catalogue_sha256") == sha256(bundle["catalogue"])
                and material.get("contract_sha256") == sha256(contract()), "PHASE2_INPUT_MATERIAL_BINDING_INVALID")
        authority = material["runtime_authority"]
        require(authority.get("ref") == "refs/heads/main" and authority.get("event") in {"schedule", "workflow_dispatch"}
                and str(authority.get("run_id", "")).isdigit()
                and bundle.get("run_id") == authority["run_id"] and bundle.get("commit_sha") == authority["commit_sha"]
                and len(authority["commit_sha"]) == 40 and all(c in "0123456789abcdef" for c in authority["commit_sha"])
                and bundle["source_provenance"].get("input_material_sha256") == sha256(material),
                "PHASE2_RUNTIME_AUTHORITY_BINDING_INVALID")
        require(bundle["input_snapshot_id"] == material["input_snapshot_id"] == input_identity(material),
                "PHASE2_INPUT_IDENTITY_INVALID")
        require(bundle["production_snapshot_id"] == material["production_snapshot_id"] == production_identity(material),
                "PHASE2_PRODUCTION_IDENTITY_INVALID")
        from scripts.publish_production_source_bundle_latest import EOD_REQUIRED_DATASETS, INTRADAY_REQUIRED_DATASETS
        required = INTRADAY_REQUIRED_DATASETS if cadence in {"09:30", "12:00"} else EOD_REQUIRED_DATASETS
        require(bundle.get("required_datasets") == required and bundle.get("datasets_present") == required,
                "PHASE2_REQUIRED_DATASETS_INCOMPLETE")
        require(validate_freshness(bundle, trading_date=trading_date, cadence=cadence)["status"] == "PASS", "PHASE2_SOURCE_FRESHNESS_FAIL")
        ranking_date = bundle["ranking_trading_date"]
        validate_catalogue(bundle["catalogue"], ranking_date)
        symbols, _ = bind_full_universe(bundle["catalogue"], contract(), ranking_date, [])
        rows = bundle["decision_records"]
        require(len(rows) == len(symbols) and {row["symbol"] for row in rows} == set(symbols)
                and bundle.get("coverage") == f"{len(symbols)}/{len(symbols)}", "FULL_MARKET_INPUTS_INCOMPLETE")
        require(bundle.get("ranking") == rank_full_market(rows), "PHASE2_RANKING_BINDING_INVALID")
        if cadence == "19:30":
            from scripts.build_production_source_bundle_from_official import build_freshness_matrix, _parse_time
            receipts = material["normalized_source_receipts"]
            require(receipts and all(r.get("normalization_status") == "PASS"
                    and _parse_time(r.get("retrieval_timestamp")) is not None for r in receipts),
                    "SOURCE_FRESHNESS_TIMESTAMP_MISSING")
            require({r["domain"] for r in receipts} == set(required), "PHASE2_REQUIRED_DATASETS_INCOMPLETE")
            for domain in ("market_daily", "benchmark", "institutional", "trading_metadata"):
                require({r["source"] for r in receipts if r["domain"] == domain} == {"TWSE", "TPEX"},
                        "PHASE2_OFFICIAL_MARKET_RECEIPTS_INCOMPLETE")
            require({r["source"] for r in receipts if r["domain"] == "large_holder"} == {"TDCC"}
                    and {r["source"] for r in receipts if r["domain"] == "fundamental"} == {"MOPS"},
                    "PHASE2_OFFICIAL_OWNER_RECEIPTS_INCOMPLETE")
            matrix = build_freshness_matrix(trading_date=trading_date, cadence=cadence,
                normalized_sources=receipts,
                retrieval_timestamp=bundle["freshness_evaluated_at"])
            require(matrix["validation_status"] == "PASS" and matrix == bundle.get("freshness_matrix"),
                    "PHASE2_SOURCE_FRESHNESS_FAIL:" + str(matrix["blocking_reasons"]))
        require(bundle.get("source_provenance", {}).get("source") == "AUTHORIZED_LIVE", "PHASE2_SOURCE_AUTHORITY_INVALID")
        if cadence in {"09:30", "12:00"}:
            require_intraday_authority()
            require(bundle.get("authorized_intraday_feed") == "PASS", EXTERNAL_FEED)
        return {"validation_status": "PASS", "retrieval_timestamp": bundle["source_provenance"]["retrieval_timestamp"],
                "required_record_count": len(symbols), "record_count": len(rows), "coverage": bundle["coverage"]}
    except (RuntimeError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return {"validation_status": "FAIL", "blocking_reason": str(exc)}


def main_authority():
    require(os.getenv("GITHUB_REF") == "refs/heads/main" and os.getenv("EXECUTION_AUTHORITY") == "MAIN_ONLY"
            and os.getenv("GITHUB_EVENT_NAME") in {"schedule", "workflow_dispatch"}
            and os.getenv("GITHUB_RUN_ID", "").isdigit()
            and os.getenv("ACTIONS_JOB_ID", "").isdigit(), "PHASE2_MAIN_AUTHORITY_REQUIRED")
    commit = os.getenv("GITHUB_SHA", "")
    require(len(commit) == 40 and all(c in "0123456789abcdef" for c in commit), "PHASE2_MAIN_AUTHORITY_REQUIRED")
    return {"run_id": os.environ["GITHUB_RUN_ID"], "commit_sha": commit,
            "event": os.environ["GITHUB_EVENT_NAME"], "ref": "refs/heads/main"}


def previous_snapshot(previous):
    decision = previous["decision"]
    snapshot = decision.get("production_snapshot_id")
    if decision.get("baseline_type") == "CONTROL_CENTER_REBASELINE":
        snapshot = decision["production_evidence_state"]["source_snapshot_id"]
    require(snapshot, "PREVIOUS_PRODUCTION_SNAPSHOT_MISSING")
    return snapshot


def input_identity(material):
    return "rate-input-snapshot-" + sha256({k: v for k, v in material.items()
        if k not in {"input_snapshot_id", "production_snapshot_id"}})[:24]


def production_identity(material):
    return "rate-source-snapshot-" + sha256({key: material[key] for key in
        ("input_snapshot_id", "trading_date", "cadence", "runtime_authority")})[:24]


def bind_input_material(raw, catalogue, previous, *, trading_date, cadence, authority):
    value = {**raw, "artifact": "RATE_FULL_MARKET_EOD_INPUTS" if cadence == "19:30" else "RATE_PHASE2_CARRIED_INPUTS",
        "evidence_scope": "PRODUCTION", "trading_date": trading_date, "cadence": cadence,
        "catalogue_sha256": sha256(catalogue), "contract_sha256": sha256(contract()),
        "validation_status": "PASS", "source_status": "PASS", "freshness_status": "PASS",
        "blocked_dependencies": [], "fallback_used": False, "runtime_authority": authority,
        "previous_state_id": previous["current_state_id"], "previous_state_hash": previous["decision_payload_hash"]}
    value["input_snapshot_id"] = input_identity(value)
    value["production_snapshot_id"] = production_identity(value)
    return value


def evaluate_material(material, catalogue, state_root):
    if material["cadence"] in {"09:30", "12:00"}:
        require_intraday_authority()
    day, time, loaded = latest_predecessor(state_root, material["trading_date"], material["cadence"])
    previous = loaded["state"]
    require(material.get("previous_state_id") == previous["current_state_id"]
            and material.get("previous_state_hash") == previous["decision_payload_hash"], "PHASE2_INPUT_LINEAGE_INVALID")
    first = material["cadence"] == "19:30" and not previous["decision"].get("short_top30")
    if first:
        validate_first_refresh(previous, state_root, material["trading_date"], material["cadence"])
    # Reuse calculations only within this process for byte-bound identical inputs.
    # Canonical predecessor/authority gates still run on every call; no source is cached here.
    key = sha256({"material": material, "catalogue": catalogue, "contract": contract(), "previous": previous})
    if material["cadence"] == "19:30" and key in _DERIVED_RESULTS:
        result = copy.deepcopy(_DERIVED_RESULTS[key])
    else:
        result = evaluate_rotation(state_root=state_root, previous_trading_date=day, previous_cadence=time,
            trading_date=material["trading_date"], cadence=material["cadence"], catalogue=catalogue,
            inputs=material, contract=contract(), intraday_feed=material.get("intraday_feed"), first_refresh=first)
    require(result["validation_status"] == "PASS", result.get("blocking_reason", "PHASE2_EVALUATION_FAILED"))
    if material["cadence"] == "19:30" and key not in _DERIVED_RESULTS:
        if len(_DERIVED_RESULTS) >= 4:
            _DERIVED_RESULTS.pop(next(iter(_DERIVED_RESULTS)))
        _DERIVED_RESULTS[key] = copy.deepcopy(result)
    if material["cadence"] != "19:30":
        require(material.get("carried_state_id") == previous["current_state_id"]
                and material.get("carried_state_hash") == previous["decision_payload_hash"]
                and catalogue == previous["decision"].get("catalogue"), "PHASE2_CARRIED_INPUT_BINDING_INVALID")
        result["ranking"] = {**result["ranking"], "records": copy.deepcopy(previous["decision"]["records"])}
        result.update(input_snapshot_id=material["input_snapshot_id"], production_snapshot_id=material["production_snapshot_id"])
        if material["cadence"] in {"09:30", "12:00"}:
            feed = material["intraday_feed"]
            require(feed.get("previous_state_id") == previous["current_state_id"]
                    and feed.get("previous_state_hash") == previous["decision_payload_hash"]
                    and feed.get("payload_references"), EXTERNAL_FEED)
            from .production_live_state import file_hash
            for reference in feed["payload_references"]:
                require(Path(reference["path"]).is_file() and file_hash(Path(reference["path"])) == reference["sha256"],
                        EXTERNAL_FEED)
    return result, previous


def bundle_from_material(material, catalogue, state_root):
    from scripts.publish_production_source_bundle_latest import EOD_REQUIRED_DATASETS, INTRADAY_REQUIRED_DATASETS
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    matrix = None
    if material["cadence"] == "19:30":
        from scripts.build_production_source_bundle_from_official import build_freshness_matrix
        matrix = build_freshness_matrix(trading_date=material["trading_date"], cadence=material["cadence"],
            normalized_sources=material["normalized_source_receipts"], retrieval_timestamp=now)
        require(matrix["validation_status"] == "PASS", "PHASE2_SOURCE_FRESHNESS_FAIL:" + str(matrix["blocking_reasons"]))
    result, previous = evaluate_material(material, catalogue, state_root)
    completed = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if matrix is not None:
        matrix = build_freshness_matrix(trading_date=material["trading_date"], cadence=material["cadence"],
            normalized_sources=material["normalized_source_receipts"], retrieval_timestamp=completed)
        require(matrix["validation_status"] == "PASS", "PHASE2_SOURCE_FRESHNESS_FAIL:" + str(matrix["blocking_reasons"]))
    required = INTRADAY_REQUIRED_DATASETS if material["cadence"] in {"09:30", "12:00"} else EOD_REQUIRED_DATASETS
    count = len(result["ranking"]["records"])
    return {"artifact": "RATE_PRODUCTION_SOURCE_BUNDLE", "schema_version": SOURCE_SCHEMA,
        "trading_date": material["trading_date"], "cadence": material["cadence"],
        "run_id": material["runtime_authority"]["run_id"], "commit_sha": material["runtime_authority"]["commit_sha"],
        "production_snapshot_id": material["production_snapshot_id"], "input_snapshot_id": material["input_snapshot_id"],
        "snapshot_id": material["production_snapshot_id"], "previous_snapshot_id": previous_snapshot(previous),
        "validation_status": "PASS", "source_status": "PASS", "freshness_status": "PASS",
        "required_datasets": required, "datasets_present": required, "datasets_missing": [], "blocked_dependencies": [],
        "domains": [{"domain": item} for item in required],
        "authorized_intraday_feed": "PASS" if material["cadence"] in {"09:30", "12:00"} else "NOT_APPLICABLE",
        "fallback_used": False, "ranking_trading_date": material["trading_date"] if material["cadence"] == "19:30"
            else previous["decision"]["ranking_trading_date"], "catalogue": catalogue,
        "input_material": material, "ranking": result["ranking"], "decision_records": result["ranking"]["records"],
        "coverage": f"{count}/{count}", "acquisition_completed_at": now,
        "freshness_evaluated_at": completed, "freshness_matrix": matrix,
        "generated_at": completed,
        "source_provenance": {"source": "AUTHORIZED_LIVE", "retrieval_timestamp": completed,
            "trading_date": material["trading_date"], "input_material_sha256": sha256(material),
            "carried_rankings": material["cadence"] != "19:30"}}


def prepare_bundle_state(bundle, *, state_root):
    validation = validate_phase2_source_bundle(bundle, trading_date=bundle["trading_date"], cadence=bundle["cadence"])
    require(validation["validation_status"] == "PASS", validation.get("blocking_reason", "PHASE2_SOURCE_INVALID"))
    result, previous = evaluate_material(bundle["input_material"], bundle["catalogue"], state_root)
    require(result["ranking"] == bundle["ranking"], "PHASE2_FEATURE_BINDING_INVALID")
    state = decision_from_evaluation(result, previous, catalogue=bundle["catalogue"],
        trading_date=bundle["trading_date"], cadence=bundle["cadence"], source_bundle_hash=sha256(bundle))
    validate_transition(previous, state, state_root=state_root, trading_date=bundle["trading_date"], cadence=bundle["cadence"])
    return state

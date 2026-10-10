"""Read-only report acceptance. Never awards CER081/full-production credit."""
from __future__ import annotations

from datetime import datetime, timezone
import math
from pathlib import Path
from urllib.parse import urlparse

from scripts.publish_production_source_bundle_latest import EOD_REQUIRED_DATASETS, validate_production_source_bundle
from scripts.build_production_source_bundle_from_official import NO_FALLBACK
from scripts.resolve_production_runtime_context import _previous_legal_trading_day, is_trading_day
from src.cer074_acceptance import sha256
from src.cer078_evening_1930 import validate_partial_evening_state
from src.production_live_state import MANIFEST_NAME, file_hash, load_live_state, read_object, require
from src.provider_eps_metadata import read_metadata
from src import public_official_partial_valid as partial

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "config/RATE_FOUR_CADENCE_REPORT_SOAK_V1.json"
KIND = "RATE-FOUR-CADENCE-REPORT-SOAK-V1"


def pinned(reference):
    path = Path(reference["path"])
    require(file_hash(path) == reference["sha256"], "REPORT_SOAK_REFERENCE_HASH_MISMATCH")
    return read_metadata(path.read_bytes())


def governance():
    contract = read_object(CONTRACT)
    dependency = next(item for item in read_object(ROOT / "config/RATE_EXTERNAL_PRODUCTION_DEPENDENCIES.json")["dependencies"]
        if item["dependency_id"] == partial.DEPENDENCY)
    require(contract["acceptance_id"] == KIND and contract["cer081_credit"] == 0
        and contract["credit_scope"] == dependency["report_soak_credit_scope"]
        and dependency["report_soak_acceptance_id"] == KIND
        and dependency["report_soak_credit_allowed_while_intraday_blocked"] is True
        and dependency["status"] == "BLOCKED_EXTERNAL", "REPORT_SOAK_GOVERNANCE_INVALID")
    for field in ("fallback_allowed", "soak_credit_allowed_while_blocked",
                  "cer081_completion_allowed_while_blocked", "production_acceptance_allowed_while_blocked"):
        require(dependency[field] is False, "REPORT_SOAK_FULL_GATE_CHANGED")
    return contract


def _load_slot(root, slot):
    day, cadence = slot["trading_date"], slot["cadence"]
    loaded = load_live_state(root, day, cadence)
    reference = slot["state_manifest"]
    require(Path(reference["path"]).resolve() == (loaded["path"].parent / MANIFEST_NAME).resolve(),
        "REPORT_SOAK_NONCANONICAL_SLOT")
    require(pinned(reference) == loaded["manifest"], "REPORT_SOAK_MANIFEST_BINDING_INVALID")
    return loaded


def _lineage(previous, current):
    before, after = previous["decision"], current["decision"]
    require(current["previous_state_id"] == previous["current_state_id"]
        and after.get("previous_state_hash") == previous["decision_payload_hash"], "REPORT_SOAK_LINEAGE_BROKEN")
    require(after.get("previous_state_resolution") == "PERSISTED_PRODUCTION_STATE"
        and not after.get("state_reinitialized") and not after.get("reset"), "REPORT_SOAK_STATE_RESET")
    for name in ("roy_portfolio", "ai_paper_portfolio", "transaction_ledger"):
        require(before[name] == after[name], "REPORT_SOAK_ACCOUNT_OR_LEDGER_CHANGED:" + name)
        if isinstance(after[name], dict):
            require(not after[name].get("reset"), "REPORT_SOAK_ACCOUNT_RESET")


def _formal_source(source, *, synthetic):
    provenance = source.get("source_provenance", {})
    require(all(provenance.get(key) == value for key, value in NO_FALLBACK.items()), "REPORT_SOAK_FALLBACK_FORBIDDEN")
    if not synthetic:
        require(source.get("synthetic_only") is not True and provenance.get("production_evidence_authoritative") is True
            and provenance.get("execution_authority") == "MAIN_ONLY", "REPORT_SOAK_LIVE_SOURCE_REQUIRED")
    datasets = source.get("official_source_transformation", {}).get("datasets", [])
    require(datasets and all(row.get("normalization_status") == "PASS" for row in datasets), "REPORT_SOAK_SOURCE_NORMALIZATION_INVALID")
    for row in datasets:
        host = urlparse(row.get("endpoint", "")).hostname
        allowed = {"openapi.twse.com.tw", "www.twse.com.tw", "www.tpex.org.tw", "www.tdcc.com.tw", "mops.twse.com.tw"}
        require(host in allowed or (synthetic and host == "example.invalid"), "REPORT_SOAK_UNAPPROVED_SOURCE")


def _eod_source(source, day):
    require(set(EOD_REQUIRED_DATASETS) <= set(source.get("datasets_present", []))
        and not source.get("datasets_missing") and source.get("freshness_matrix", {}).get("validation_status") == "PASS",
        "REPORT_SOAK_EOD_SOURCE_INVALID")
    datasets = source["official_source_transformation"]["datasets"]
    for row in source.get("eod_close_records", []):
        require(row.get("trade_date") == day and any(d.get("domain") == "market_daily"
            and all(d.get(key) == row.get(key) for key in ("source", "dataset_id", "body_sha256", "parser_version")) for d in datasets),
            "REPORT_SOAK_EOD_PRICE_SOURCE_INVALID")
        for key in ("close", "volume", "turnover"):
            value = row.get(key)
            require(type(value) in (int, float) and math.isfinite(value)
                and (value > 0 if key == "close" else value >= 0), "REPORT_SOAK_EOD_PRICE_INVALID")


def evaluate(*, evidence, state_root):
    contract = governance()
    require(evidence.get("artifact") == KIND + "-INPUT", "REPORT_SOAK_INPUT_IDENTITY_INVALID")
    runs = evidence["runs"]
    require(isinstance(runs, list), "REPORT_SOAK_RUNS_INVALID")
    # Manual runs never receive credit; conflicting event declarations cannot mask a dispatch.
    runs = [run for run in runs if run.get("event_name") == "schedule"
        and run.get("event", "schedule") == "schedule"]
    slots = [(run["trading_date"], run["cadence"]) for run in runs]
    require(len(slots) == len(set(slots)), "REPORT_SOAK_DUPLICATE_SLOT")
    days = sorted({day for day, _ in slots})
    require(all(is_trading_day(day) for day in days), "REPORT_SOAK_NONTRADING_DAY")
    for previous, day in zip(days, days[1:]):
        require(_previous_legal_trading_day(day) == previous, "REPORT_SOAK_TRADING_DAY_GAP")
    runs.sort(key=lambda run: (run["trading_date"], contract["cadences"].index(run["cadence"])))
    boundary = _load_slot(state_root, evidence["predecessor"])["state"]
    if days:
        require(boundary["decision"]["cadence"] == "19:30"
            and boundary["decision"]["trading_date"] == _previous_legal_trading_day(days[0]),
            "REPORT_SOAK_BOUNDARY_INVALID")
    previous = boundary
    accepted, run_ids = [], set()
    synthetic = evidence.get("synthetic_only") is True
    for run in runs:
        day, cadence = run["trading_date"], run["cadence"]
        loaded = _load_slot(state_root, run)
        state, manifest = loaded["state"], loaded["manifest"]
        require(manifest["event_name"] == "schedule" and not manifest.get("recovery_mode")
            and not manifest.get("rebaseline_bootstrap"), "REPORT_SOAK_SCHEDULE_REQUIRED")
        require(manifest["workflow_run_id"] not in run_ids, "REPORT_SOAK_DUPLICATE_RUN_ID")
        run_ids.add(manifest["workflow_run_id"])
        context = pinned(run["runtime_context"])
        require(context.get("validation_status") == "PASS" and context.get("event_name") == "schedule"
            and context.get("runtime_mode") == "RUN" and context.get("cadence") == cadence
            and context.get("trading_date") == day and context.get("previous_state_id") == previous["current_state_id"]
            and context.get("previous_state_hash") == previous["decision_payload_hash"]
            and context.get("production_persistent_state_reset_count") == 0, "REPORT_SOAK_CONTEXT_INVALID")
        _lineage(previous, state)
        decision = state["decision"]
        source = pinned(run["source_bundle"])
        checked = partial.timestamp(run["source_validated_at"])
        require(checked <= datetime.now(timezone.utc), "REPORT_SOAK_FUTURE_VALIDATION")
        if cadence in ("09:30", "12:00"):
            partial.validate_partial_state(decision)
            require(decision["public_official_bundle"] == source, "REPORT_SOAK_SOURCE_BINDING_INVALID")
            partial.validate_bundle(source, trading_date=day, cadence=cadence, as_of=checked.isoformat())
            require(decision.get("trade_intent_status") == "PRESERVED_NOT_EXECUTED"
                and decision.get("scheduled_soak_credit") is False, "REPORT_SOAK_INTRADAY_EXECUTION")
        else:
            require(validate_production_source_bundle(source, trading_date=day, cadence=cadence, now=checked)["validation_status"] == "PASS",
                "REPORT_SOAK_OFFICIAL_SOURCE_INVALID")
            _formal_source(source, synthetic=synthetic)
            if cadence == "19:30":
                validate_partial_evening_state(decision)
                require(decision.get("eod_source_bundle") == source
                    and decision.get("evening_closure") == {"validation_status": "PASS", "new_transactions": [], "state_reinitialized": False},
                    "REPORT_SOAK_EOD_CLOSURE_INVALID")
                _eod_source(source, day)
            else:
                require(decision.get("source_bundle_hash") == sha256(source), "REPORT_SOAK_SOURCE_BINDING_INVALID")
        accepted.append({"trading_date": day, "cadence": cadence, "workflow_run_id": manifest["workflow_run_id"],
            "previous_state_id": state["previous_state_id"], "current_state_id": state["current_state_id"],
            "current_state_hash": state["decision_payload_hash"], "state_manifest": run["state_manifest"],
            "source_bundle": run["source_bundle"], "source_validated_at": run["source_validated_at"],
            "report_runtime_status": decision.get("report_runtime_status", "PRODUCTION_REPORT_VALID"),
            "report_soak_credit": 1, "cer081_credit": 0, "ai_paper_intraday_executions": 0, "new_intraday_fills": 0})
        previous = state
    complete_days = [day for day in days if all((day, c) in slots for c in contract["cadences"])]
    complete = (len(complete_days) >= contract["required_trading_days"] and len(accepted) >= contract["required_scheduled_runs"])
    return {"artifact": KIND, "validation_status": "PASS" if complete else "NOT_ACCEPTED",
        "RATE_REPORT_PRODUCTION_SOAK": "PASS" if complete else "HOLD",
        "CER081_FULL_PRODUCTION_SOAK": "BLOCKED_EXTERNAL", "cer081_credit": 0,
        "evidence_scope": "SYNTHETIC_ENGINEERING_ONLY" if synthetic else "SCHEDULED_PRODUCTION_EVIDENCE",
        "live_scheduled_report_credit": 0 if synthetic else len(accepted),
        "report_soak_credit_scope": contract["credit_scope"], "report_soak_credit_allowed_while_intraday_blocked": True,
        "trading_days": len(complete_days), "scheduled_runs": len(accepted), "intraday_chains": len(complete_days),
        "cross_day_transitions": sum(1 for a, b in zip(runs, runs[1:]) if a["cadence"] == "19:30" and b["cadence"] == "07:30"),
        "runs": accepted, "contract_sha256": file_hash(CONTRACT), "input_content_sha256": sha256(evidence),
        "full_production_acceptance": "NOT_ALLOWED", "fallback_allowed": False,
        "external_dependency_status": "BLOCKED_EXTERNAL", "production_acceptance_granted": False}

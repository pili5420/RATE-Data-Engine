from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cer074_acceptance import atomic_write_json, sha256, strip_runtime
from src.production_live_state import (CADENCE_DIR, MANIFEST_NAME, PERSIST_NAME, STATE_NAME,
                                       REBASELINE_PERSIST_ARTIFACT, file_hash, read_object,
                                       require, validate_rebaseline_material)

AUTHORIZATION_NAME = "RATE_PRODUCTION_REBASELINE_AUTHORIZATION_MANIFEST.json"
CONSUMPTION_NAME = "RATE_PRODUCTION_REBASELINE_AUTHORIZATION_CONSUMPTION_EVIDENCE.json"
BOOTSTRAP_EVIDENCE_NAME = "RATE_PRODUCTION_REBASELINE_BOOTSTRAP_EVIDENCE.json"
AUTHORIZATION_ROOT = Path("control") / "rebaseline_authorizations"
APPROVED_MATERIAL_ROOT = Path("artifacts") / "rebaseline_material"
FORBIDDEN_PARTS = {"fixture", "fixtures", "staging", "cache", "synthetic", "recovery",
                   "recovery_authorizations", "production_state"}
CADENCE_ORDER = {cadence: index for index, cadence in enumerate(CADENCE_DIR)}
CADENCE_BY_DIR = {directory: cadence for cadence, directory in CADENCE_DIR.items()}


def _canonical_hash(payload):
    clone = dict(payload)
    clone.pop("manifest_integrity_hash", None)
    clone.pop("authorization_blob_sha256", None)
    clone.pop("approval_commit_sha", None)
    blob = json.dumps(clone, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _canonical_equal(left, right):
    return json.dumps(left, ensure_ascii=False, sort_keys=True, separators=(",", ":")) == json.dumps(
        right, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _without_artifact(value):
    if isinstance(value, dict):
        return {k: v for k, v in value.items() if k != "artifact"}
    return value


def _safe_authorization_id(value):
    require(isinstance(value, str) and value.startswith("CC-"), "REBASELINE_BOOTSTRAP_AUTHORIZATION_REQUIRED")
    require(all(c.isalnum() or c in "-_." for c in value), "REBASELINE_BOOTSTRAP_AUTHORIZATION_REQUIRED")
    return value


def _git(repository_root, *args):
    result = subprocess.run(["git", "-C", str(repository_root), *args], capture_output=True, text=True)
    require(result.returncode == 0, result.stderr.strip() or "REBASELINE_AUTHORIZATION_GIT_VALIDATION_FAILED")
    return result.stdout.strip()


def _authorization_path(repository_root, authorization_id):
    relative = AUTHORIZATION_ROOT / authorization_id / AUTHORIZATION_NAME
    path = Path(repository_root) / relative
    require(path.resolve().is_relative_to((Path(repository_root) / AUTHORIZATION_ROOT).resolve()),
            "REBASELINE_AUTHORIZATION_PATH_INVALID")
    return relative, path


def _validate_approval_commit(repository_root, relative_path, authorization, current_main_sha):
    approval = authorization.get("approval_commit_sha")
    require(isinstance(approval, str) and len(approval) == 40 and all(c in "0123456789abcdef" for c in approval),
            "REBASELINE_APPROVAL_COMMIT_INVALID")
    for commit in (approval, current_main_sha):
        result = subprocess.run(["git", "-C", str(repository_root), "cat-file", "-e", f"{commit}^{{commit}}"],
                                capture_output=True, text=True)
        require(result.returncode == 0, "REBASELINE_APPROVAL_COMMIT_INVALID")
    ancestor = subprocess.run(["git", "-C", str(repository_root), "merge-base", "--is-ancestor", approval,
                               current_main_sha], capture_output=True, text=True)
    require(ancestor.returncode == 0, "REBASELINE_APPROVAL_COMMIT_NOT_MAIN_ANCESTOR")
    committed = json.loads(_git(repository_root, "show", f"{approval}:{relative_path.as_posix()}"))
    require(_canonical_hash(committed) == _canonical_hash(authorization),
            "REBASELINE_AUTHORIZATION_BYTES_CHANGED_AFTER_APPROVAL")
    require(_canonical_hash(authorization) == authorization.get("authorization_blob_sha256"),
            "REBASELINE_AUTHORIZATION_BLOB_HASH_MISMATCH")


def _safe_material_path(repository_root, raw_path):
    raw = Path(raw_path)
    require(not raw.is_absolute(), "REBASELINE_MATERIAL_PATH_INVALID")
    require(".." not in raw.parts, "REBASELINE_MATERIAL_PATH_INVALID")
    require(not (FORBIDDEN_PARTS & {part.lower() for part in raw.parts}), "REBASELINE_MATERIAL_PATH_INVALID")
    repo = Path(repository_root).resolve()
    approved = (repo / APPROVED_MATERIAL_ROOT).resolve()
    candidate = (repo / raw).resolve(strict=True)
    require(candidate.is_file() and candidate.is_relative_to(approved), "REBASELINE_MATERIAL_PATH_INVALID")
    return candidate


def _check_hashes(manifest, hashes):
    files = manifest.get("files") or {}
    for key, value in hashes.items():
        require(files.get(key) == value, "REBASELINE_MATERIAL_FILE_HASH_MISMATCH")


def _validation_value(payload, *keys):
    for key in keys:
        if key in payload:
            return payload[key]
    nested = payload.get("production_data_validation") or payload.get("source_validation") or {}
    for key in keys:
        if key in nested:
            return nested[key]
    return None


def _coverage_complete(source_bundle):
    coverage = source_bundle.get("coverage") or (source_bundle.get("decision_record_coverage") or {}).get("coverage")
    coverage_obj = source_bundle.get("decision_record_coverage") or {}
    actual = coverage_obj.get("actual") or coverage_obj.get("records") or source_bundle.get("decision_records_count")
    required = coverage_obj.get("required") or source_bundle.get("required_decision_records")
    records = source_bundle.get("decision_records")
    if isinstance(records, list):
        actual = len(records)
    return coverage == "30/30" and actual == 30 and (required in {None, 30})


def _validate_source_bundle(source_bundle, trading_date, cadence):
    require(source_bundle.get("artifact") == "RATE_PRODUCTION_SOURCE_BUNDLE",
            "REBASELINE_PRODUCTION_SOURCE_BINDING_MISMATCH")
    require(source_bundle.get("validation_status") == "PASS", "REBASELINE_PRODUCTION_SOURCE_BINDING_MISMATCH")
    require(source_bundle.get("trading_date") == trading_date and source_bundle.get("cadence") == cadence,
            "REBASELINE_PRODUCTION_SOURCE_BINDING_MISMATCH")
    require(_validation_value(source_bundle, "freshness") == "PASS", "REBASELINE_PRODUCTION_SOURCE_BINDING_MISMATCH")
    require(_validation_value(source_bundle, "completeness") == "PASS",
            "REBASELINE_PRODUCTION_SOURCE_BINDING_MISMATCH")
    require(_coverage_complete(source_bundle), "REBASELINE_PRODUCTION_SOURCE_BINDING_MISMATCH")
    require(isinstance(source_bundle.get("source_snapshot_id"), str) and source_bundle["source_snapshot_id"],
            "REBASELINE_PRODUCTION_SOURCE_BINDING_MISMATCH")
    require(isinstance(source_bundle.get("input_snapshot_ids"), list) and bool(source_bundle["input_snapshot_ids"])
            and all(isinstance(item, str) and item for item in source_bundle["input_snapshot_ids"]),
            "REBASELINE_PRODUCTION_SOURCE_BINDING_MISMATCH")
    provenance = source_bundle.get("source_provenance") or {}
    for key in ("future_dated", "stale", "fixture", "staging", "local_cache", "synthetic", "recovery",
                "historical_acceptance_fallback"):
        require(provenance.get(key) in {None, False, "FORBIDDEN"}, "REBASELINE_PRODUCTION_SOURCE_BINDING_MISMATCH")
    return {"source_snapshot_id": source_bundle["source_snapshot_id"],
            "input_snapshot_ids": source_bundle["input_snapshot_ids"], "coverage": "30/30",
            "freshness": "PASS", "completeness": "PASS", "validation_status": "PASS",
            "source_provenance": provenance}


def _validate_embedded_production_evidence(decision, source_bundle, source_bundle_hash, trading_date, cadence):
    require(decision.get("production_source_bundle_sha256") == source_bundle_hash,
            "REBASELINE_PRODUCTION_EVIDENCE_BINDING_MISMATCH")
    evidence = decision.get("production_evidence_state") or {}
    expected = _validate_source_bundle(source_bundle, trading_date, cadence)
    require(evidence.get("validation_status") == expected["validation_status"], "REBASELINE_PRODUCTION_EVIDENCE_BINDING_MISMATCH")
    require(evidence.get("trading_date") == trading_date and evidence.get("cadence") == cadence,
            "REBASELINE_PRODUCTION_EVIDENCE_BINDING_MISMATCH")
    require(evidence.get("source_snapshot_id") == expected["source_snapshot_id"], "REBASELINE_PRODUCTION_EVIDENCE_BINDING_MISMATCH")
    require(evidence.get("input_snapshot_ids") == expected["input_snapshot_ids"], "REBASELINE_PRODUCTION_EVIDENCE_BINDING_MISMATCH")
    require(evidence.get("coverage") == expected["coverage"] and evidence.get("freshness") == "PASS"
            and evidence.get("completeness") == "PASS", "REBASELINE_PRODUCTION_EVIDENCE_BINDING_MISMATCH")
    require(_canonical_equal(evidence.get("source_provenance") or {}, expected["source_provenance"]),
            "REBASELINE_PRODUCTION_EVIDENCE_BINDING_MISMATCH")


def _validate_roy_binding(roy, decision):
    require(roy.get("artifact") == "CONTROL_CENTER_REBASELINE_ROY_OPENING_STATE",
            "REBASELINE_ROY_STATE_BINDING_MISMATCH")
    require(_canonical_equal(_without_artifact(roy), decision.get("roy_portfolio")),
            "REBASELINE_ROY_STATE_BINDING_MISMATCH")
    require(roy.get("source_type") == "CONTROL_CENTER_APPROVED_ROY_PORTFOLIO_OPENING_STATE",
            "REBASELINE_ROY_STATE_BINDING_MISMATCH")
    require(roy.get("currency") == "TWD", "REBASELINE_ROY_STATE_BINDING_MISMATCH")
    positions = roy.get("positions")
    require(isinstance(positions, list) and positions, "REBASELINE_ROY_STATE_BINDING_MISMATCH")
    for position in positions:
        for key in ("symbol", "quantity", "average_cost", "currency"):
            require(key in position, "REBASELINE_ROY_STATE_BINDING_MISMATCH")
        require(position.get("synthetic") is not True, "REBASELINE_ROY_STATE_BINDING_MISMATCH")
    totals = roy.get("totals") or {}
    for key in ("cash", "opening_nav", "stock_market_value", "stock_total_cost"):
        require(key in totals, "REBASELINE_ROY_STATE_BINDING_MISMATCH")


def _validate_ai_binding(ai, decision):
    require(ai.get("artifact") == "CONTROL_CENTER_REBASELINE_AI_OPENING_STATE",
            "REBASELINE_AI_STATE_BINDING_MISMATCH")
    require(_canonical_equal(_without_artifact(ai), decision.get("ai_paper_portfolio")),
            "REBASELINE_AI_STATE_BINDING_MISMATCH")
    require(ai.get("source_type") == "AI_PAPER_PORTFOLIO_REBASELINE_OPENING_STATE",
            "REBASELINE_AI_STATE_BINDING_MISMATCH")
    require(ai.get("opening_capital") == 1000000 and ai.get("positions") == []
            and ai.get("cash") == 1000000 and ai.get("nav") == 1000000 and ai.get("currency") == "TWD",
            "REBASELINE_AI_STATE_BINDING_MISMATCH")
    require(ai.get("historical_pnl_carried_forward") is False
            and ai.get("historical_transactions_carried_forward") is False
            and ai.get("historical_recovery") is False, "REBASELINE_AI_STATE_BINDING_MISMATCH")


def _validate_ledger_binding(ledger, decision):
    require(ledger.get("artifact") == "RATE_LEDGER_REBASELINE_BOUNDARY", "REBASELINE_LEDGER_BINDING_MISMATCH")
    require(_canonical_equal(_without_artifact(ledger), decision.get("transaction_ledger")),
            "REBASELINE_LEDGER_BINDING_MISMATCH")
    expected = {"event_type": "REBASELINE_OPENING_BALANCE",
                "pre_rebaseline_transaction_history": "UNAVAILABLE",
                "historical_transaction_reconstruction": "PROHIBITED",
                "ledger_continuity_mode": "POST_REBASELINE_ONLY",
                "historical_recovery_status": "HISTORICAL_RECOVERY_SOURCE_IRRECOVERABLE"}
    for key, value in expected.items():
        require(ledger.get(key) == value, "REBASELINE_LEDGER_BINDING_MISMATCH")
    require("historical_terminal_reference" in ledger and "roy_portfolio_reference" in ledger
            and "ai_paper_portfolio_reference" in ledger, "REBASELINE_LEDGER_BINDING_MISMATCH")
    require("transactions" not in ledger and "historical_transactions" not in ledger,
            "REBASELINE_LEDGER_BINDING_MISMATCH")


def _build_rebaseline_persist_and_state(rebaseline_state, trading_date, cadence):
    decision = rebaseline_state.get("decision") if isinstance(rebaseline_state.get("decision"), dict) else rebaseline_state
    digest = sha256(strip_runtime(decision))
    state_id = "rate-state-" + digest[:24]
    state = {"current_state_id": state_id, "decision_payload_hash": digest, "decision": decision}
    entry = {"current_state_id": state_id, "decision_payload_hash": digest, "trading_date": trading_date,
             "cadence": cadence, "execution_scope": "PRODUCTION", "baseline_type": "CONTROL_CENTER_REBASELINE",
             "previous_state_resolution": "CONTROL_CENTER_REBASELINE",
             "historical_chain_break_acknowledged": True, "historical_account_state_recoverable": False}
    material = {"artifact": "RATE_PRODUCTION_DECISION_STATE", "validation_status": "PASS",
                "state_entry": entry, "decision_state": {**state, "state_entry": entry}}
    persist = {"artifact": REBASELINE_PERSIST_ARTIFACT, "validation_status": "PASS",
               "current_state_id": state_id, "current_state_hash": digest,
               "baseline_type": "CONTROL_CENTER_REBASELINE",
               "previous_state_resolution": "CONTROL_CENTER_REBASELINE",
               "persist_result": {"status": "PERSISTED", "state_entry": entry}}
    return persist, material, state_id, digest


def validate_material_package(*, manifest, rebaseline_state, source_bundle, roy, ai, ledger,
                              hashes, trading_date, cadence, authorization):
    require(manifest.get("artifact") == "RATE_PRODUCTION_REBASELINE_MANIFEST"
            and manifest.get("validation_status") == "PASS", "REBASELINE_BOOTSTRAP_BLOCKED")
    baseline_id = authorization.get("baseline_id")
    require(isinstance(baseline_id, str) and baseline_id, "REBASELINE_BASELINE_ID_MISMATCH")
    require(manifest.get("baseline_type") == "CONTROL_CENTER_REBASELINE", "REBASELINE_BOOTSTRAP_BLOCKED")
    require(manifest.get("baseline_id") == baseline_id, "REBASELINE_BASELINE_ID_MISMATCH")
    require(manifest.get("selected_trading_date") == trading_date and manifest.get("selected_cadence") == cadence,
            "REBASELINE_PRODUCTION_SOURCE_BINDING_MISMATCH")
    _check_hashes(manifest, hashes)
    decision = rebaseline_state.get("decision") if isinstance(rebaseline_state.get("decision"), dict) else rebaseline_state
    require(decision.get("baseline_id") == baseline_id, "REBASELINE_BASELINE_ID_MISMATCH")
    require(decision.get("trading_date") == trading_date and decision.get("cadence") == cadence,
            "REBASELINE_PRODUCTION_SOURCE_BINDING_MISMATCH")
    require(decision.get("execution_scope") == "PRODUCTION", "REBASELINE_PRODUCTION_SOURCE_BINDING_MISMATCH")
    _validate_source_bundle(source_bundle, trading_date, cadence)
    _validate_embedded_production_evidence(decision, source_bundle, hashes["RATE_PRODUCTION_SOURCE_BUNDLE.json"],
                                           trading_date, cadence)
    _validate_roy_binding(roy, decision)
    _validate_ai_binding(ai, decision)
    _validate_ledger_binding(ledger, decision)
    persist, material, state_id, digest = _build_rebaseline_persist_and_state(rebaseline_state, trading_date, cadence)
    state = validate_rebaseline_material(persist, material, trading_date, cadence)
    require(state["current_state_id"] == state_id and state["decision_payload_hash"] == digest,
            "REBASELINE_BOOTSTRAP_BLOCKED")
    require(rebaseline_state.get("state_id") == state_id and rebaseline_state.get("state_hash") == digest,
            "REBASELINE_MATERIAL_STATE_HASH_MISMATCH")
    require(manifest.get("state_id") == state_id and manifest.get("state_hash") == digest,
            "REBASELINE_MATERIAL_STATE_HASH_MISMATCH")
    require(state_id == authorization.get("expected_state_id") and digest == authorization.get("expected_state_hash"),
            "REBASELINE_MATERIAL_STATE_HASH_MISMATCH")
    return persist, material, state_id, digest


def _fsync_file(path):
    try:
        with open(path, "rb") as handle:
            os.fsync(handle.fileno())
    except OSError:
        pass


def _fsync_dir(path):
    if os.name != "posix":
        return
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _atomic_write_json_fsync(path, value):
    atomic_write_json(path, value)
    _fsync_file(path)
    _fsync_dir(path.parent)


def _live_directory(root, trading_date, cadence):
    directory = root / "production_state" / "live" / trading_date / CADENCE_DIR[cadence]
    require(directory.resolve().is_relative_to((root / "production_state").resolve()), "LIVE_STATE_PATH_ESCAPE")
    return directory


def _build_consumption(authorization, authorization_id, trading_date, cadence, workflow_run_id, workflow_job_id,
                       commit_sha, state_id, state_hash):
    return {"artifact": "RATE_PRODUCTION_REBASELINE_AUTHORIZATION_CONSUMPTION_EVIDENCE",
            "validation_status": "PASS", "authorization_id": authorization_id, "consumed": True,
            "consumed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "workflow_run_id": workflow_run_id, "workflow_job_id": workflow_job_id, "commit_sha": commit_sha,
            "baseline_id": authorization.get("baseline_id"), "source_state_id": state_id,
            "source_state_hash": state_hash, "target_trading_date": trading_date, "target_cadence": cadence,
            "approval_commit_sha": authorization["approval_commit_sha"],
            "authorization_blob_sha256": authorization["authorization_blob_sha256"],
            "scheduled_soak_credit": False, "acceptance_counter_reset": False,
            "post_rebaseline_continuity_window": "NEW"}


def _build_live_manifest(*, trading_date, cadence, event_name, ref, commit_sha, workflow_run_id, workflow_job_id,
                         authorization, authorization_id, state_id, state_hash, files):
    return {"artifact": "RATE_PRODUCTION_STATE_MANIFEST", "validation_status": "PASS",
            "trading_date": trading_date, "cadence": cadence, "event_name": event_name, "ref": ref,
            "commit_sha": commit_sha, "workflow_run_id": workflow_run_id, "workflow_job_id": workflow_job_id,
            "baseline_type": "CONTROL_CENTER_REBASELINE", "rebaseline_bootstrap": True,
            "historical_chain_break_acknowledged": True, "scheduled_soak_credit": False,
            "acceptance_counter_reset": False, "post_rebaseline_continuity_window": "NEW",
            "rebaseline_authorization_id": authorization_id,
            "approval_commit_sha": authorization["approval_commit_sha"],
            "rebaseline_authorization_manifest_hash": authorization["manifest_integrity_hash"],
            "authorization_blob_sha256": authorization["authorization_blob_sha256"],
            "baseline_id": authorization.get("baseline_id"), "baseline_state_id": state_id,
            "baseline_state_hash": state_hash, "current_state_id": state_id, "current_state_hash": state_hash,
            "files": files}


def _write_latest_atomic(root, *, trading_date, cadence, workflow_run_id, workflow_job_id, authorization_id,
                         baseline_id, state_id, state_hash, live_dir):
    manifest_path = live_dir / MANIFEST_NAME
    consumption_path = live_dir / CONSUMPTION_NAME
    latest = {"artifact": "RATE_PRODUCTION_STATE_LATEST", "validation_status": "PASS",
              "trading_date": trading_date, "cadence": cadence,
              "workflow_run_id": workflow_run_id, "workflow_job_id": workflow_job_id,
              "current_state_id": state_id, "current_state_hash": state_hash,
              "live_state_evidence_path": (live_dir / PERSIST_NAME).as_posix(),
              "live_manifest_path": manifest_path.as_posix(), "live_manifest_sha256": file_hash(manifest_path),
              "authorization_consumption_path": consumption_path.as_posix(),
              "authorization_consumption_sha256": file_hash(consumption_path),
              "baseline_id": baseline_id, "baseline_type": "CONTROL_CENTER_REBASELINE",
              "rebaseline_bootstrap": True, "scheduled_soak_credit": False,
              "acceptance_counter_reset": False, "post_rebaseline_continuity_window": "NEW",
              "rebaseline_authorization_id": authorization_id}
    target = root / "RATE_PRODUCTION_STATE_LATEST.json"
    tmp = root / f"RATE_PRODUCTION_STATE_LATEST.json.tmp.{authorization_id}"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(latest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    _fsync_file(tmp)
    os.replace(tmp, target)
    _fsync_file(target)
    _fsync_dir(target.parent)
    return latest


def _validate_live_slot(live_dir, *, authorization_id, baseline_id, state_id, state_hash):
    for name in (PERSIST_NAME, STATE_NAME, MANIFEST_NAME, CONSUMPTION_NAME):
        require((live_dir / name).is_file(), "REBASELINE_PARTIAL_PUBLICATION_INVALID")
    manifest = read_object(live_dir / MANIFEST_NAME)
    consumption = read_object(live_dir / CONSUMPTION_NAME)
    require(manifest.get("rebaseline_authorization_id") == authorization_id
            and manifest.get("baseline_id") == baseline_id
            and manifest.get("current_state_id") == state_id
            and manifest.get("current_state_hash") == state_hash, "LIVE_STATE_CANONICAL_SLOT_EXISTS")
    require(consumption.get("authorization_id") == authorization_id and consumption.get("consumed") is True
            and consumption.get("baseline_id") == baseline_id
            and consumption.get("source_state_id") == state_id
            and consumption.get("source_state_hash") == state_hash, "REBASELINE_PARTIAL_PUBLICATION_INVALID")
    for name in (PERSIST_NAME, STATE_NAME, CONSUMPTION_NAME):
        require(file_hash(live_dir / name) == (manifest.get("files") or {}).get(name),
                "REBASELINE_PARTIAL_PUBLICATION_INVALID")
    return manifest, consumption


def _latest_matches(root, *, authorization_id, baseline_id, state_id, state_hash, trading_date, cadence):
    path = root / "RATE_PRODUCTION_STATE_LATEST.json"
    if not path.is_file():
        return False
    latest = read_object(path)
    return (latest.get("rebaseline_authorization_id") == authorization_id
            and latest.get("baseline_id") == baseline_id
            and latest.get("current_state_id") == state_id
            and latest.get("current_state_hash") == state_hash
            and latest.get("trading_date") == trading_date
            and latest.get("cadence") == cadence)


def _slot_key(trading_date, cadence):
    require(trading_date and cadence in CADENCE_ORDER, "REBASELINE_LATEST_CONFLICT")
    return trading_date, CADENCE_ORDER[cadence]


def _compare_slots(left_date, left_cadence, right_date, right_cadence):
    left = _slot_key(left_date, left_cadence)
    right = _slot_key(right_date, right_cadence)
    return (left > right) - (left < right)


def _newer_canonical_live_state_exists(root, *, trading_date, cadence, state_id, state_hash):
    live_root = root / "production_state" / "live"
    if not live_root.is_dir():
        return False
    for manifest_path in live_root.glob("*/" + "*/" + MANIFEST_NAME):
        cadence_name = CADENCE_BY_DIR.get(manifest_path.parent.name)
        date_name = manifest_path.parent.parent.name
        if not cadence_name:
            continue
        manifest = read_object(manifest_path)
        require(manifest.get("trading_date") == date_name and manifest.get("cadence") == cadence_name,
                "REBASELINE_LATEST_CONFLICT")
        slot_cmp = _compare_slots(date_name, cadence_name, trading_date, cadence)
        if slot_cmp > 0:
            return True
        if slot_cmp == 0 and (manifest.get("current_state_id") != state_id
                              or manifest.get("current_state_hash") != state_hash):
            raise RuntimeError("REBASELINE_LATEST_CONFLICT")
    return False


def _latest_is_same_baseline(latest, *, authorization_id, baseline_id, state_id, state_hash, trading_date, cadence):
    return (latest.get("rebaseline_authorization_id") == authorization_id
            and latest.get("baseline_id") == baseline_id
            and latest.get("trading_date") == trading_date
            and latest.get("cadence") == cadence
            and latest.get("baseline_type") == "CONTROL_CENTER_REBASELINE"
            and latest.get("rebaseline_bootstrap") is True
            and latest.get("current_state_id") == state_id
            and latest.get("current_state_hash") == state_hash)


def _latest_repair_status(root, *, authorization_id, baseline_id, state_id, state_hash, trading_date, cadence):
    latest_path = root / "RATE_PRODUCTION_STATE_LATEST.json"
    if _newer_canonical_live_state_exists(root, trading_date=trading_date, cadence=cadence,
                                          state_id=state_id, state_hash=state_hash):
        return "REBASELINE_LATEST_ALREADY_ADVANCED"
    if not latest_path.is_file():
        return "REBASELINE_LATEST_REPAIR_ELIGIBLE"
    latest = read_object(latest_path)
    if _latest_is_same_baseline(latest, authorization_id=authorization_id, baseline_id=baseline_id,
                                state_id=state_id, state_hash=state_hash,
                                trading_date=trading_date, cadence=cadence):
        return "REBASELINE_AUTHORIZATION_ALREADY_CONSUMED"
    latest_date = latest.get("trading_date")
    latest_cadence = latest.get("cadence")
    same_auth_pending = (latest.get("rebaseline_authorization_id") == authorization_id
                         and latest.get("baseline_id") == baseline_id
                         and latest.get("current_state_id") in {None, state_id}
                         and latest.get("current_state_hash") in {None, state_hash}
                         and latest.get("latest_update_status") in {"PENDING", "BOOTSTRAP_PENDING", "INCOMPLETE"})
    if latest_date and latest_cadence in CADENCE_ORDER:
        slot_cmp = _compare_slots(latest_date, latest_cadence, trading_date, cadence)
        if slot_cmp > 0:
            return "REBASELINE_LATEST_ALREADY_ADVANCED"
        if slot_cmp < 0:
            return "REBASELINE_LATEST_REPAIR_ELIGIBLE"
        if same_auth_pending:
            return "REBASELINE_LATEST_REPAIR_ELIGIBLE"
        if slot_cmp == 0:
            return "REBASELINE_LATEST_CONFLICT"

    if same_auth_pending:
        return "REBASELINE_LATEST_REPAIR_ELIGIBLE"
    return "REBASELINE_LATEST_CONFLICT"


def _stage_package(staging_dir, *, persist, material, consumption, trading_date, cadence, event_name, ref, commit_sha,
                   workflow_run_id, workflow_job_id, authorization, authorization_id, state_id, state_hash,
                   simulate_crash_at=None):
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=False)
    _atomic_write_json_fsync(staging_dir / STATE_NAME, material)
    if simulate_crash_at == "after_one_staged_file":
        raise RuntimeError("REBASELINE_STAGING_INCOMPLETE")
    _atomic_write_json_fsync(staging_dir / PERSIST_NAME, persist)
    _atomic_write_json_fsync(staging_dir / CONSUMPTION_NAME, consumption)
    evidence = {"artifact": "RATE_PRODUCTION_REBASELINE_BOOTSTRAP_EVIDENCE", "validation_status": "PASS",
                "atomic_publication_stage": "STAGED_CANONICAL_PACKAGE", "latest_update_status": "PENDING",
                "baseline_id": authorization.get("baseline_id"), "source_state_id": state_id,
                "source_state_hash": state_hash, "trading_date": trading_date, "cadence": cadence,
                "rebaseline_authorization_id": authorization_id, "scheduled_soak_credit": False,
                "acceptance_counter_reset": False, "post_rebaseline_continuity_window": "NEW"}
    _atomic_write_json_fsync(staging_dir / BOOTSTRAP_EVIDENCE_NAME, evidence)
    files = {name: file_hash(staging_dir / name) for name in (PERSIST_NAME, STATE_NAME, CONSUMPTION_NAME)}
    live_manifest = _build_live_manifest(trading_date=trading_date, cadence=cadence, event_name=event_name, ref=ref,
                                         commit_sha=commit_sha, workflow_run_id=workflow_run_id,
                                         workflow_job_id=workflow_job_id, authorization=authorization,
                                         authorization_id=authorization_id, state_id=state_id,
                                         state_hash=state_hash, files=files)
    _atomic_write_json_fsync(staging_dir / MANIFEST_NAME, live_manifest)
    if simulate_crash_at == "staging_hash_mismatch":
        (staging_dir / PERSIST_NAME).write_text("{}\n", encoding="utf-8")
    _validate_live_slot(staging_dir, authorization_id=authorization_id, baseline_id=authorization.get("baseline_id"),
                        state_id=state_id, state_hash=state_hash)
    validate_rebaseline_material(read_object(staging_dir / PERSIST_NAME), read_object(staging_dir / STATE_NAME),
                                 trading_date, cadence)
    return live_manifest


def bootstrap_rebaseline_state(*, rebaseline_manifest_path, rebaseline_state_path, source_bundle_path,
                               roy_opening_state_path, ai_opening_state_path, ledger_boundary_path,
                               trading_date, cadence, rebaseline_authorization_id,
                               artifacts_root="artifacts", workflow_run_id=None, workflow_job_id=None,
                               event_name=None, commit_sha=None, ref=None, evidence_output=None,
                               repository_root=".", simulate_crash_at=None):
    out = {"artifact": "RATE_PRODUCTION_REBASELINE_BOOTSTRAP_EVIDENCE", "validation_status": "BLOCKED",
           "baseline_type": "CONTROL_CENTER_REBASELINE", "trading_date": trading_date, "cadence": cadence,
           "rebaseline_bootstrap": True, "scheduled_soak_credit": False, "acceptance_counter_reset": False,
           "post_rebaseline_continuity_window": "NEW", "rebaseline_authorization_id": rebaseline_authorization_id,
           "workflow_run_id": workflow_run_id, "workflow_job_id": workflow_job_id,
           "atomic_publication": True, "material_path_namespace": APPROVED_MATERIAL_ROOT.as_posix()}
    try:
        event_name = event_name or os.getenv("GITHUB_EVENT_NAME")
        commit_sha = commit_sha or os.getenv("GITHUB_SHA")
        ref = ref or os.getenv("GITHUB_REF")
        require(event_name == "workflow_dispatch" and ref == "refs/heads/main",
                "REBASELINE_BOOTSTRAP_AUTHORIZATION_REQUIRED")
        require(str(workflow_run_id or "").isdigit() and str(workflow_job_id or "").isdigit()
                and isinstance(commit_sha, str) and len(commit_sha) == 40
                and all(c in "0123456789abcdef" for c in commit_sha),
                "REBASELINE_BOOTSTRAP_AUTHORIZATION_REQUIRED")
        authorization_id = _safe_authorization_id(rebaseline_authorization_id)
        repository_root = Path(repository_root).resolve()
        relative_authorization_path, authorization_manifest_path = _authorization_path(repository_root, authorization_id)
        require(authorization_manifest_path.is_file(), "REBASELINE_AUTHORIZATION_MANIFEST_REQUIRED")
        authorization = read_object(authorization_manifest_path)
        require(authorization.get("artifact") == "RATE_PRODUCTION_REBASELINE_AUTHORIZATION_MANIFEST",
                "REBASELINE_AUTHORIZATION_MANIFEST_INVALID")
        require(authorization.get("manifest_integrity_hash") == _canonical_hash(authorization),
                "REBASELINE_AUTHORIZATION_MANIFEST_TAMPERED")
        _validate_approval_commit(repository_root, relative_authorization_path, authorization, commit_sha)
        require(authorization.get("authorization_id") == authorization_id, "REBASELINE_AUTHORIZATION_ID_MISMATCH")
        require(authorization.get("authorization_status") == "APPROVED"
                and authorization.get("approved_by") == "CONTROL_CENTER", "REBASELINE_AUTHORIZATION_NOT_APPROVED")
        require(authorization.get("baseline_type") == "CONTROL_CENTER_REBASELINE"
                and authorization.get("previous_state_resolution") == "CONTROL_CENTER_REBASELINE",
                "REBASELINE_AUTHORIZATION_POLICY_INVALID")
        require(authorization.get("single_use") is True
                and authorization.get("acceptance_counter_reset") is False
                and authorization.get("post_rebaseline_continuity_window") == "NEW",
                "REBASELINE_AUTHORIZATION_POLICY_INVALID")
        require(authorization.get("trading_date") == trading_date and authorization.get("cadence") == cadence,
                "REBASELINE_AUTHORIZATION_TARGET_MISMATCH")

        material_paths = {
            "RATE_PRODUCTION_REBASELINE_MANIFEST.json": _safe_material_path(repository_root, rebaseline_manifest_path),
            "RATE_PRODUCTION_REBASELINE_DECISION_STATE.json": _safe_material_path(repository_root, rebaseline_state_path),
            "RATE_PRODUCTION_SOURCE_BUNDLE.json": _safe_material_path(repository_root, source_bundle_path),
            "CONTROL_CENTER_REBASELINE_ROY_OPENING_STATE.json": _safe_material_path(repository_root, roy_opening_state_path),
            "CONTROL_CENTER_REBASELINE_AI_OPENING_STATE.json": _safe_material_path(repository_root, ai_opening_state_path),
            "RATE_LEDGER_REBASELINE_BOUNDARY.json": _safe_material_path(repository_root, ledger_boundary_path),
        }
        manifest = read_object(material_paths["RATE_PRODUCTION_REBASELINE_MANIFEST.json"])
        rebaseline_state = read_object(material_paths["RATE_PRODUCTION_REBASELINE_DECISION_STATE.json"])
        source_bundle = read_object(material_paths["RATE_PRODUCTION_SOURCE_BUNDLE.json"])
        roy = read_object(material_paths["CONTROL_CENTER_REBASELINE_ROY_OPENING_STATE.json"])
        ai = read_object(material_paths["CONTROL_CENTER_REBASELINE_AI_OPENING_STATE.json"])
        ledger = read_object(material_paths["RATE_LEDGER_REBASELINE_BOUNDARY.json"])
        hashes = {name: file_hash(path) for name, path in material_paths.items()
                  if name != "RATE_PRODUCTION_REBASELINE_MANIFEST.json"}
        require(hashes["RATE_PRODUCTION_SOURCE_BUNDLE.json"] == authorization.get("production_source_bundle_sha256"),
                "REBASELINE_PRODUCTION_BUNDLE_HASH_MISMATCH")
        require(hashes["CONTROL_CENTER_REBASELINE_ROY_OPENING_STATE.json"] == authorization.get("roy_opening_state_sha256"),
                "REBASELINE_ROY_OPENING_HASH_MISMATCH")
        require(hashes["CONTROL_CENTER_REBASELINE_AI_OPENING_STATE.json"] == authorization.get("ai_opening_state_sha256"),
                "REBASELINE_AI_OPENING_HASH_MISMATCH")
        require(hashes["RATE_LEDGER_REBASELINE_BOUNDARY.json"] == authorization.get("ledger_boundary_sha256"),
                "REBASELINE_LEDGER_BOUNDARY_HASH_MISMATCH")
        require(hashes["RATE_PRODUCTION_REBASELINE_DECISION_STATE.json"] == authorization.get("canonical_rebaseline_state_sha256"),
                "REBASELINE_CANONICAL_STATE_FILE_HASH_MISMATCH")
        persist, material, state_id, state_hash = validate_material_package(
            manifest=manifest, rebaseline_state=rebaseline_state, source_bundle=source_bundle,
            roy=roy, ai=ai, ledger=ledger, hashes=hashes, trading_date=trading_date, cadence=cadence,
            authorization=authorization)

        root = Path(artifacts_root).resolve()
        live_dir = _live_directory(root, trading_date, cadence)
        baseline_id = authorization.get("baseline_id")
        if live_dir.exists():
            _validate_live_slot(live_dir, authorization_id=authorization_id, baseline_id=baseline_id,
                                state_id=state_id, state_hash=state_hash)
            latest_status = _latest_repair_status(root, authorization_id=authorization_id, baseline_id=baseline_id,
                                                  state_id=state_id, state_hash=state_hash,
                                                  trading_date=trading_date, cadence=cadence)
            if latest_status == "REBASELINE_AUTHORIZATION_ALREADY_CONSUMED":
                raise RuntimeError("REBASELINE_AUTHORIZATION_ALREADY_CONSUMED")
            if latest_status != "REBASELINE_LATEST_REPAIR_ELIGIBLE":
                raise RuntimeError(latest_status)
            _write_latest_atomic(root, trading_date=trading_date, cadence=cadence,
                                 workflow_run_id=workflow_run_id, workflow_job_id=workflow_job_id,
                                 authorization_id=authorization_id, baseline_id=baseline_id,
                                 state_id=state_id, state_hash=state_hash, live_dir=live_dir)
            out.update(validation_status="PASS", live_state_updated=False, idempotent_latest_repair=True,
                       latest_repair_eligibility="REBASELINE_LATEST_REPAIR_ELIGIBLE",
                       latest_pointer_path=(root / "RATE_PRODUCTION_STATE_LATEST.json").as_posix(),
                       latest_pointer_sha256=file_hash(root / "RATE_PRODUCTION_STATE_LATEST.json"),
                       destination_live_state_path=(live_dir / PERSIST_NAME).as_posix(),
                       authorization_consumption_path=(live_dir / CONSUMPTION_NAME).as_posix(),
                       source_state_id=state_id, source_state_hash=state_hash, baseline_id=baseline_id)
            return out

        staging_dir = root / "production_state" / ".staging" / authorization_id / trading_date / CADENCE_DIR[cadence]
        consumption = _build_consumption(authorization, authorization_id, trading_date, cadence, workflow_run_id,
                                         workflow_job_id, commit_sha, state_id, state_hash)
        _stage_package(staging_dir, persist=persist, material=material, consumption=consumption,
                       trading_date=trading_date, cadence=cadence, event_name=event_name, ref=ref,
                       commit_sha=commit_sha, workflow_run_id=workflow_run_id, workflow_job_id=workflow_job_id,
                       authorization=authorization, authorization_id=authorization_id, state_id=state_id,
                       state_hash=state_hash, simulate_crash_at=simulate_crash_at)
        if simulate_crash_at == "before_atomic_promotion":
            raise RuntimeError("REBASELINE_STAGING_NOT_PROMOTED")
        live_dir.parent.mkdir(parents=True, exist_ok=True)
        require(not live_dir.exists(), "LIVE_STATE_CANONICAL_SLOT_EXISTS")
        os.replace(staging_dir, live_dir)
        _fsync_dir(live_dir.parent)
        if simulate_crash_at == "after_live_promotion_before_latest":
            raise RuntimeError("LIVE_SLOT_PUBLISHED_LATEST_UPDATE_FAILED")
        _validate_live_slot(live_dir, authorization_id=authorization_id, baseline_id=baseline_id,
                            state_id=state_id, state_hash=state_hash)
        try:
            _write_latest_atomic(root, trading_date=trading_date, cadence=cadence,
                                 workflow_run_id=workflow_run_id, workflow_job_id=workflow_job_id,
                                 authorization_id=authorization_id, baseline_id=baseline_id,
                                 state_id=state_id, state_hash=state_hash, live_dir=live_dir)
        except OSError as exc:
            out["latest_update_status"] = "LIVE_SLOT_PUBLISHED_LATEST_UPDATE_FAILED"
            raise RuntimeError("LIVE_SLOT_PUBLISHED_LATEST_UPDATE_FAILED") from exc
        out.update(validation_status="PASS", live_state_updated=True,
                   latest_pointer_path=(root / "RATE_PRODUCTION_STATE_LATEST.json").as_posix(),
                   latest_pointer_sha256=file_hash(root / "RATE_PRODUCTION_STATE_LATEST.json"),
                   destination_live_state_path=(live_dir / PERSIST_NAME).as_posix(),
                   authorization_consumption_path=(live_dir / CONSUMPTION_NAME).as_posix(),
                   source_state_id=state_id, source_state_hash=state_hash,
                   baseline_id=baseline_id, atomic_publication_status="PASS")
    except (RuntimeError, OSError, ValueError, KeyError, TypeError) as exc:
        reason = str(exc)
        out["blocking_reason"] = reason
        if reason in {"REBASELINE_STAGING_INCOMPLETE", "REBASELINE_STAGING_NOT_PROMOTED",
                      "REBASELINE_PARTIAL_PUBLICATION_INVALID"}:
            root = Path(artifacts_root).resolve()
            staging_root = root / "production_state" / ".staging" / str(rebaseline_authorization_id)
            if staging_root.exists():
                shutil.rmtree(staging_root)
    if evidence_output:
        atomic_write_json(Path(evidence_output), out)
    return out


def main():
    parser = argparse.ArgumentParser(description="Authorized RATE Control Center rebaseline bootstrap.")
    parser.add_argument("--rebaseline-manifest", required=True)
    parser.add_argument("--rebaseline-state", required=True)
    parser.add_argument("--source-bundle", required=True)
    parser.add_argument("--roy-opening-state", required=True)
    parser.add_argument("--ai-opening-state", required=True)
    parser.add_argument("--ledger-boundary", required=True)
    parser.add_argument("--trading-date", required=True)
    parser.add_argument("--cadence", required=True, choices=sorted(CADENCE_DIR))
    parser.add_argument("--rebaseline-authorization-id", required=True)
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--artifacts-root", default="artifacts")
    parser.add_argument("--workflow-run-id")
    parser.add_argument("--workflow-job-id")
    parser.add_argument("--evidence-output",
                        default="artifacts/production_state/RATE_PRODUCTION_REBASELINE_BOOTSTRAP_EVIDENCE.json")
    args = parser.parse_args()
    out = bootstrap_rebaseline_state(rebaseline_manifest_path=args.rebaseline_manifest,
                                     rebaseline_state_path=args.rebaseline_state,
                                     source_bundle_path=args.source_bundle,
                                     roy_opening_state_path=args.roy_opening_state,
                                     ai_opening_state_path=args.ai_opening_state,
                                     ledger_boundary_path=args.ledger_boundary,
                                     trading_date=args.trading_date, cadence=args.cadence,
                                     rebaseline_authorization_id=args.rebaseline_authorization_id,
                                     repository_root=args.repository_root,
                                     artifacts_root=args.artifacts_root,
                                     workflow_run_id=args.workflow_run_id,
                                     workflow_job_id=args.workflow_job_id,
                                     evidence_output=args.evidence_output)
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))
    return 0 if out["validation_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

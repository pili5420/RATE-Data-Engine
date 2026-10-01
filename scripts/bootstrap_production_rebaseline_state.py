from __future__ import annotations

import argparse
import hashlib
import json
import os
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
FORBIDDEN_PARTS = {"fixture", "fixtures", "staging", "cache", "synthetic", "recovery_authorizations"}


def _canonical_hash(payload):
    clone = dict(payload)
    clone.pop("manifest_integrity_hash", None)
    clone.pop("authorization_blob_sha256", None)
    clone.pop("approval_commit_sha", None)
    blob = json.dumps(clone, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


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
    ancestor = subprocess.run(["git", "-C", str(repository_root), "merge-base", "--is-ancestor", approval, current_main_sha],
                              capture_output=True, text=True)
    require(ancestor.returncode == 0, "REBASELINE_APPROVAL_COMMIT_NOT_MAIN_ANCESTOR")
    committed = json.loads(_git(repository_root, "show", f"{approval}:{relative_path.as_posix()}"))
    require(_canonical_hash(committed) == _canonical_hash(authorization),
            "REBASELINE_AUTHORIZATION_BYTES_CHANGED_AFTER_APPROVAL")
    require(_canonical_hash(authorization) == authorization.get("authorization_blob_sha256"),
            "REBASELINE_AUTHORIZATION_BLOB_HASH_MISMATCH")


def _forbid_path(path, reason="REBASELINE_SOURCE_FALLBACK_FORBIDDEN"):
    parts = {part.lower() for part in Path(path).parts}
    require(not (FORBIDDEN_PARTS & parts), reason)


def _material_manifest_hash(manifest, name, path):
    expected = (manifest.get("files") or {}).get(name)
    require(isinstance(expected, str) and expected == file_hash(path), "REBASELINE_MATERIAL_FILE_HASH_MISMATCH")


def _build_rebaseline_persist_and_state(rebaseline_state, trading_date, cadence):
    decision = rebaseline_state.get("decision") if isinstance(rebaseline_state.get("decision"), dict) else rebaseline_state
    digest = sha256(strip_runtime(decision))
    state_id = "rate-state-" + digest[:24]
    state = {"current_state_id": state_id, "decision_payload_hash": digest, "decision": decision}
    entry = {"current_state_id": state_id, "decision_payload_hash": digest,
             "trading_date": trading_date, "cadence": cadence, "execution_scope": "PRODUCTION",
             "baseline_type": "CONTROL_CENTER_REBASELINE",
             "previous_state_resolution": "CONTROL_CENTER_REBASELINE",
             "historical_chain_break_acknowledged": True,
             "historical_account_state_recoverable": False}
    material = {"artifact": "RATE_PRODUCTION_DECISION_STATE", "validation_status": "PASS",
                "state_entry": entry, "decision_state": {**state, "state_entry": entry}}
    persist = {"artifact": REBASELINE_PERSIST_ARTIFACT, "validation_status": "PASS",
               "current_state_id": state_id, "current_state_hash": digest,
               "baseline_type": "CONTROL_CENTER_REBASELINE",
               "previous_state_resolution": "CONTROL_CENTER_REBASELINE",
               "persist_result": {"status": "PERSISTED", "state_entry": entry}}
    return persist, material, state_id, digest


def validate_material_package(*, manifest, rebaseline_state, source_bundle, roy, ai, ledger,
                              hashes, trading_date, cadence):
    require(manifest.get("artifact") == "RATE_PRODUCTION_REBASELINE_MANIFEST"
            and manifest.get("validation_status") == "PASS", "REBASELINE_BOOTSTRAP_BLOCKED")
    require(manifest.get("baseline_type") == "CONTROL_CENTER_REBASELINE", "REBASELINE_BOOTSTRAP_BLOCKED")
    require(manifest.get("selected_trading_date") == trading_date and manifest.get("selected_cadence") == cadence,
            "REBASELINE_BOOTSTRAP_BLOCKED")
    files = manifest.get("files") or {}
    for key, value in hashes.items():
        require(files.get(key) == value, "REBASELINE_MATERIAL_FILE_HASH_MISMATCH")
    require(source_bundle.get("validation_status") == "PASS", "REBASELINE_BOOTSTRAP_BLOCKED")
    coverage = source_bundle.get("coverage") or source_bundle.get("decision_record_coverage", {}).get("coverage")
    require(coverage == "30/30", "REBASELINE_BOOTSTRAP_BLOCKED")
    require(roy.get("source_type") == "CONTROL_CENTER_APPROVED_ROY_PORTFOLIO_OPENING_STATE", "REBASELINE_BOOTSTRAP_BLOCKED")
    require(ai.get("source_type") == "AI_PAPER_PORTFOLIO_REBASELINE_OPENING_STATE", "REBASELINE_BOOTSTRAP_BLOCKED")
    require(ledger.get("event_type") == "REBASELINE_OPENING_BALANCE", "REBASELINE_BOOTSTRAP_BLOCKED")
    persist, material, state_id, digest = _build_rebaseline_persist_and_state(rebaseline_state, trading_date, cadence)
    state = validate_rebaseline_material(persist, material, trading_date, cadence)
    require(state["current_state_id"] == state_id and state["decision_payload_hash"] == digest, "REBASELINE_BOOTSTRAP_BLOCKED")
    require(manifest.get("state_id") == state_id and manifest.get("state_hash") == digest,
            "REBASELINE_MATERIAL_STATE_HASH_MISMATCH")
    return persist, material, state_id, digest


def bootstrap_rebaseline_state(*, rebaseline_manifest_path, rebaseline_state_path, source_bundle_path,
                               roy_opening_state_path, ai_opening_state_path, ledger_boundary_path,
                               trading_date, cadence, rebaseline_authorization_id,
                               artifacts_root="artifacts", workflow_run_id=None, workflow_job_id=None,
                               event_name=None, commit_sha=None, ref=None, evidence_output=None,
                               repository_root="."):
    out = {"artifact": "RATE_PRODUCTION_REBASELINE_BOOTSTRAP_EVIDENCE", "validation_status": "BLOCKED",
           "baseline_type": "CONTROL_CENTER_REBASELINE", "trading_date": trading_date, "cadence": cadence,
           "rebaseline_bootstrap": True, "scheduled_soak_credit": False, "acceptance_counter_reset": False,
           "post_rebaseline_continuity_window": "NEW", "rebaseline_authorization_id": rebaseline_authorization_id,
           "workflow_run_id": workflow_run_id, "workflow_job_id": workflow_job_id}
    try:
        event_name = event_name or os.getenv("GITHUB_EVENT_NAME")
        commit_sha = commit_sha or os.getenv("GITHUB_SHA")
        ref = ref or os.getenv("GITHUB_REF")
        require(event_name == "workflow_dispatch" and ref == "refs/heads/main", "REBASELINE_BOOTSTRAP_AUTHORIZATION_REQUIRED")
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

        for source_path in (rebaseline_manifest_path, rebaseline_state_path, source_bundle_path,
                            roy_opening_state_path, ai_opening_state_path, ledger_boundary_path):
            _forbid_path(source_path)
        manifest = read_object(rebaseline_manifest_path)
        rebaseline_state = read_object(rebaseline_state_path)
        source_bundle = read_object(source_bundle_path)
        roy = read_object(roy_opening_state_path)
        ai = read_object(ai_opening_state_path)
        ledger = read_object(ledger_boundary_path)
        hashes = {
            "RATE_PRODUCTION_SOURCE_BUNDLE.json": file_hash(source_bundle_path),
            "CONTROL_CENTER_REBASELINE_ROY_OPENING_STATE.json": file_hash(roy_opening_state_path),
            "CONTROL_CENTER_REBASELINE_AI_OPENING_STATE.json": file_hash(ai_opening_state_path),
            "RATE_LEDGER_REBASELINE_BOUNDARY.json": file_hash(ledger_boundary_path),
            "RATE_PRODUCTION_REBASELINE_DECISION_STATE.json": file_hash(rebaseline_state_path),
        }
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
            roy=roy, ai=ai, ledger=ledger, hashes=hashes, trading_date=trading_date, cadence=cadence)
        require(state_id == authorization.get("expected_state_id") and state_hash == authorization.get("expected_state_hash"),
                "REBASELINE_MATERIAL_STATE_HASH_MISMATCH")

        root = Path(artifacts_root)
        directory = root / "production_state" / "live" / trading_date / CADENCE_DIR[cadence]
        require(directory.resolve().is_relative_to((root / "production_state").resolve()), "LIVE_STATE_PATH_ESCAPE")
        consumption_dir = root / "production_state" / "rebaseline_authorizations" / authorization_id
        consumption_path = consumption_dir / CONSUMPTION_NAME
        require(not consumption_path.exists(), "REBASELINE_AUTHORIZATION_ALREADY_CONSUMED")
        for name in (PERSIST_NAME, STATE_NAME, MANIFEST_NAME):
            require(not (directory / name).exists(), "LIVE_STATE_CANONICAL_SLOT_EXISTS")

        atomic_write_json(directory / STATE_NAME, material)
        atomic_write_json(directory / PERSIST_NAME, persist)
        live_manifest = {"artifact": "RATE_PRODUCTION_STATE_MANIFEST", "validation_status": "PASS",
                         "trading_date": trading_date, "cadence": cadence, "event_name": event_name,
                         "ref": ref, "commit_sha": commit_sha, "workflow_run_id": workflow_run_id,
                         "workflow_job_id": workflow_job_id, "baseline_type": "CONTROL_CENTER_REBASELINE",
                         "rebaseline_bootstrap": True, "historical_chain_break_acknowledged": True,
                         "scheduled_soak_credit": False, "acceptance_counter_reset": False,
                         "post_rebaseline_continuity_window": "NEW",
                         "rebaseline_authorization_id": authorization_id,
                         "approval_commit_sha": authorization["approval_commit_sha"],
                         "rebaseline_authorization_manifest_hash": authorization["manifest_integrity_hash"],
                         "authorization_blob_sha256": authorization["authorization_blob_sha256"],
                         "baseline_id": authorization.get("baseline_id"),
                         "baseline_state_id": state_id, "baseline_state_hash": state_hash,
                         "current_state_id": state_id, "current_state_hash": state_hash,
                         "files": {name: file_hash(directory / name) for name in (PERSIST_NAME, STATE_NAME)}}
        atomic_write_json(directory / MANIFEST_NAME, live_manifest)
        atomic_write_json(root / "RATE_PRODUCTION_STATE_LATEST.json", {"artifact": "RATE_PRODUCTION_STATE_LATEST",
            "validation_status": "PASS", "trading_date": trading_date, "cadence": cadence,
            "workflow_run_id": workflow_run_id, "workflow_job_id": workflow_job_id,
            "current_state_id": state_id, "current_state_hash": state_hash,
            "live_state_evidence_path": (directory / PERSIST_NAME).as_posix(),
            "baseline_type": "CONTROL_CENTER_REBASELINE", "rebaseline_bootstrap": True,
            "scheduled_soak_credit": False, "acceptance_counter_reset": False,
            "post_rebaseline_continuity_window": "NEW", "rebaseline_authorization_id": authorization_id})
        consumption = {"artifact": "RATE_PRODUCTION_REBASELINE_AUTHORIZATION_CONSUMPTION_EVIDENCE",
                       "validation_status": "PASS", "authorization_id": authorization_id, "consumed": True,
                       "consumed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                       "workflow_run_id": workflow_run_id, "workflow_job_id": workflow_job_id,
                       "commit_sha": commit_sha, "baseline_id": authorization.get("baseline_id"),
                       "source_state_id": state_id, "source_state_hash": state_hash,
                       "target_trading_date": trading_date, "target_cadence": cadence,
                       "approval_commit_sha": authorization["approval_commit_sha"],
                       "authorization_blob_sha256": authorization["authorization_blob_sha256"],
                       "scheduled_soak_credit": False, "acceptance_counter_reset": False,
                       "post_rebaseline_continuity_window": "NEW"}
        atomic_write_json(consumption_path, consumption)
        out.update(validation_status="PASS", live_state_updated=True,
                   destination_live_state_path=(directory / PERSIST_NAME).as_posix(),
                   authorization_consumption_path=consumption_path.as_posix(),
                   source_state_id=state_id, source_state_hash=state_hash,
                   baseline_id=authorization.get("baseline_id"))
    except (RuntimeError, OSError, ValueError, KeyError, TypeError) as exc:
        out["blocking_reason"] = str(exc)
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
    parser.add_argument("--evidence-output", default="artifacts/production_state/RATE_PRODUCTION_REBASELINE_BOOTSTRAP_EVIDENCE.json")
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

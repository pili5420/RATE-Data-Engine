from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.cer074_acceptance import atomic_write_json, sha256, strip_runtime
from src.production_live_state import file_hash
from scripts.bootstrap_production_rebaseline_state import validate_material_package

ROY_OPENING_INPUT_PATH = Path("control/rebaseline_inputs/RATE_REBASELINE_ROY_OPENING_STATE_V1.json")
ROY_TOTALS = {"cash": 179523, "opening_nav": 1509636, "stock_market_value": 1330113, "stock_total_cost": 1972438}


def canonical_hash(value: Any) -> str:
    return sha256(strip_runtime(value))


def load_roy_opening_state(path: str | Path = ROY_OPENING_INPUT_PATH) -> dict[str, Any]:
    roy = json.loads(Path(path).read_text(encoding="utf-8"))
    if roy.get("artifact") != "CONTROL_CENTER_REBASELINE_ROY_OPENING_STATE":
        raise RuntimeError("REBASELINE_ROY_OPENING_STATE_INVALID")
    if roy.get("source_type") != "CONTROL_CENTER_APPROVED_ROY_PORTFOLIO_OPENING_STATE":
        raise RuntimeError("REBASELINE_ROY_OPENING_STATE_INVALID")
    if roy.get("currency") != "TWD" or roy.get("control_center_approved") is not True:
        raise RuntimeError("REBASELINE_ROY_OPENING_STATE_INVALID")
    positions = roy.get("positions")
    if roy.get("positions_count") != 10 or not isinstance(positions, list) or len(positions) != 10:
        raise RuntimeError("REBASELINE_ROY_OPENING_STATE_INVALID")
    for position in positions:
        if not isinstance(position, dict) or position.get("synthetic") is True:
            raise RuntimeError("REBASELINE_ROY_OPENING_STATE_INVALID")
        for key in ("symbol", "security_name", "quantity", "average_cost", "currency"):
            if key not in position:
                raise RuntimeError("REBASELINE_ROY_OPENING_STATE_INVALID")
        if not isinstance(position["quantity"], (int, float)) or isinstance(position["quantity"], bool) or position["quantity"] <= 0:
            raise RuntimeError("REBASELINE_ROY_OPENING_STATE_INVALID")
        if not isinstance(position["average_cost"], (int, float)) or isinstance(position["average_cost"], bool) or position["average_cost"] <= 0:
            raise RuntimeError("REBASELINE_ROY_OPENING_STATE_INVALID")
        if position.get("currency") != "TWD":
            raise RuntimeError("REBASELINE_ROY_OPENING_STATE_INVALID")
    if roy.get("totals") != ROY_TOTALS:
        raise RuntimeError("REBASELINE_ROY_OPENING_STATE_INVALID")
    if roy.get("synthetic_position_created") is not False or roy.get("default_zero_balance_used") is not False:
        raise RuntimeError("REBASELINE_ROY_OPENING_STATE_INVALID")
    return roy


def build_rebaseline_material(*, source_bundle_path: str | Path, output_root: str | Path = "artifacts/rebaseline_material", roy_opening_state_path: str | Path = ROY_OPENING_INPUT_PATH) -> dict[str, Any]:
    source_bundle_path = Path(source_bundle_path)
    source_bundle = json.loads(source_bundle_path.read_text(encoding="utf-8"))
    trading_date = source_bundle.get("trading_date")
    cadence = source_bundle.get("cadence")
    if source_bundle.get("validation_status") != "PASS" or source_bundle.get("source_bundle_validation") != "PASS":
        raise RuntimeError("REBASELINE_SOURCE_BUNDLE_NOT_PASS")
    if cadence != "19:30":
        raise RuntimeError("REBASELINE_SOURCE_CADENCE_NOT_1930")
    baseline_id = f"rate-rebaseline-{str(trading_date).replace('-', '')}-1930-cc-approved-v1"
    material_root = Path(output_root) / baseline_id
    material_root.mkdir(parents=True, exist_ok=True)

    roy = load_roy_opening_state(roy_opening_state_path)
    ai = {
        "artifact": "CONTROL_CENTER_REBASELINE_AI_OPENING_STATE",
        "source_type": "AI_PAPER_PORTFOLIO_REBASELINE_OPENING_STATE",
        "opening_state_type": "CONTROL_CENTER_REBASELINE_OPENING_STATE",
        "opening_capital": 1000000,
        "cash": 1000000,
        "nav": 1000000,
        "positions": [],
        "currency": "TWD",
        "historical_pnl_carried_forward": False,
        "historical_transactions_carried_forward": False,
        "historical_recovery": False,
    }
    ledger = {
        "artifact": "RATE_LEDGER_REBASELINE_BOUNDARY",
        "event_type": "REBASELINE_OPENING_BALANCE",
        "pre_rebaseline_transaction_history": "UNAVAILABLE",
        "historical_transaction_reconstruction": "PROHIBITED",
        "ledger_continuity_mode": "POST_REBASELINE_ONLY",
        "historical_recovery_status": "HISTORICAL_RECOVERY_SOURCE_IRRECOVERABLE",
        "historical_terminal_reference": {
            "trading_date": "2026-09-18",
            "cadence": "19:30",
            "state_id": "rate-state-656e460995324fb4a3eb7b30",
            "state_hash": "656e460995324fb4a3eb7b3033b754752997c8cb761d414083a2148eb150b5c7",
        },
        "roy_portfolio_reference": "CONTROL_CENTER_REBASELINE_ROY_OPENING_STATE.json",
        "ai_paper_portfolio_reference": "CONTROL_CENTER_REBASELINE_AI_OPENING_STATE.json",
    }

    source_target = material_root / "RATE_PRODUCTION_SOURCE_BUNDLE.json"
    atomic_write_json(source_target, source_bundle)
    source_hash = file_hash(source_target)
    decision = {
        "baseline_id": baseline_id,
        "baseline_type": "CONTROL_CENTER_REBASELINE",
        "baseline_version": "V1",
        "trading_date": trading_date,
        "cadence": cadence,
        "execution_scope": "PRODUCTION",
        "previous_state_resolution": "CONTROL_CENTER_REBASELINE",
        "historical_chain_break_acknowledged": True,
        "historical_account_state_recoverable": False,
        "production_source_bundle_sha256": source_hash,
        "production_evidence_state": {
            "validation_status": "PASS",
            "trading_date": trading_date,
            "cadence": cadence,
            "freshness": source_bundle.get("freshness"),
            "completeness": source_bundle.get("completeness"),
            "coverage": source_bundle.get("coverage"),
            "source_snapshot_id": source_bundle.get("source_snapshot_id"),
            "input_snapshot_ids": source_bundle.get("input_snapshot_ids"),
            "source_provenance": source_bundle.get("source_provenance"),
            "fixture_fallback": "FORBIDDEN",
            "stale_snapshot_fallback": "FORBIDDEN",
            "synthetic_fallback": "FORBIDDEN",
            "recovery_fallback": "FORBIDDEN",
            "historical_acceptance_bundle_fallback": "FORBIDDEN",
        },
        "roy_portfolio": {k: v for k, v in roy.items() if k != "artifact"},
        "ai_paper_portfolio": {k: v for k, v in ai.items() if k != "artifact"},
        "transaction_ledger": {k: v for k, v in ledger.items() if k != "artifact"},
        "historical_predecessor_reference": ledger["historical_terminal_reference"],
    }
    digest = canonical_hash(decision)
    state_id = "rate-state-" + digest[:24]
    state = {"artifact": "RATE_PRODUCTION_REBASELINE_DECISION_STATE", "validation_status": "PASS", "baseline_id": baseline_id, "state_id": state_id, "state_hash": digest, "decision": decision}

    paths = {
        "roy": material_root / "CONTROL_CENTER_REBASELINE_ROY_OPENING_STATE.json",
        "ai": material_root / "CONTROL_CENTER_REBASELINE_AI_OPENING_STATE.json",
        "ledger": material_root / "RATE_LEDGER_REBASELINE_BOUNDARY.json",
        "state": material_root / "RATE_PRODUCTION_REBASELINE_DECISION_STATE.json",
        "manifest": material_root / "RATE_PRODUCTION_REBASELINE_MANIFEST.json",
    }
    for key, obj in (("roy", roy), ("ai", ai), ("ledger", ledger), ("state", state)):
        atomic_write_json(paths[key], obj)
    manifest = {
        "artifact": "RATE_PRODUCTION_REBASELINE_MANIFEST",
        "validation_status": "PASS",
        "baseline_type": "CONTROL_CENTER_REBASELINE",
        "baseline_id": baseline_id,
        "selected_trading_date": trading_date,
        "selected_cadence": cadence,
        "state_id": state_id,
        "state_hash": digest,
        "files": {
            "RATE_PRODUCTION_SOURCE_BUNDLE.json": file_hash(source_target),
            "CONTROL_CENTER_REBASELINE_ROY_OPENING_STATE.json": file_hash(paths["roy"]),
            "CONTROL_CENTER_REBASELINE_AI_OPENING_STATE.json": file_hash(paths["ai"]),
            "RATE_LEDGER_REBASELINE_BOUNDARY.json": file_hash(paths["ledger"]),
            "RATE_PRODUCTION_REBASELINE_DECISION_STATE.json": file_hash(paths["state"]),
        },
    }
    atomic_write_json(paths["manifest"], manifest)
    hashes = {name: digest for name, digest in manifest["files"].items() if name != "RATE_PRODUCTION_REBASELINE_MANIFEST.json"}
    authorization = {
        "baseline_id": baseline_id,
        "expected_state_id": state_id,
        "expected_state_hash": digest,
        "production_source_bundle_sha256": manifest["files"]["RATE_PRODUCTION_SOURCE_BUNDLE.json"],
        "roy_opening_state_sha256": manifest["files"]["CONTROL_CENTER_REBASELINE_ROY_OPENING_STATE.json"],
        "ai_opening_state_sha256": manifest["files"]["CONTROL_CENTER_REBASELINE_AI_OPENING_STATE.json"],
        "ledger_boundary_sha256": manifest["files"]["RATE_LEDGER_REBASELINE_BOUNDARY.json"],
        "canonical_rebaseline_state_sha256": manifest["files"]["RATE_PRODUCTION_REBASELINE_DECISION_STATE.json"],
    }
    validate_material_package(manifest=manifest, rebaseline_state=state, source_bundle=source_bundle, roy=roy, ai=ai, ledger=ledger, hashes=hashes, trading_date=trading_date, cadence=cadence, authorization=authorization)
    evidence = {
        "artifact": "RATE_PRODUCTION_REBASELINE_MATERIAL_DRY_RUN_EVIDENCE",
        "validation_status": "PASS",
        "material_status": "REBASELINE_MATERIAL_READY_FOR_CONTROL_CENTER_REVIEW",
        "baseline_id": baseline_id,
        "state_id": state_id,
        "state_hash": digest,
        "material_root": material_root.as_posix(),
        "manifest_sha256": file_hash(paths["manifest"]),
        "production_source_binding": "PASS",
        "roy_opening_state_binding": "PASS",
        "ai_opening_state_binding": "PASS",
        "ledger_boundary_binding": "PASS",
        "canonical_cross_binding": "PASS",
        "identity_determinism": "PASS",
        "live_namespace_touched": False,
        "latest_touched": False,
        "authorization_created": False,
        "bootstrap_dispatched": False,
    }
    atomic_write_json(material_root / "RATE_PRODUCTION_REBASELINE_MATERIAL_DRY_RUN_EVIDENCE.json", evidence)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Build RATE production rebaseline material dry-run package from a PASS 19:30 source bundle.")
    parser.add_argument("--source-bundle", required=True)
    parser.add_argument("--output-root", default="artifacts/rebaseline_material")
    parser.add_argument("--roy-opening-state", default=str(ROY_OPENING_INPUT_PATH))
    args = parser.parse_args()
    evidence = build_rebaseline_material(source_bundle_path=args.source_bundle, output_root=args.output_root, roy_opening_state_path=args.roy_opening_state)
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0 if evidence["validation_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.cer074_acceptance import atomic_write_json, load_json

DEST = "artifacts/production_state/live/{trading_date}/1930/RATE_PRODUCTION_PERSIST_RESULT_EVIDENCE.json"


def seed(*, source_evidence_path: str | Path, artifacts_root: str | Path = "artifacts", evidence_output: str | Path | None = None) -> dict[str, Any]:
    source = load_json(source_evidence_path)
    if source.get("validation_status") != "PASS":
        raise RuntimeError("SEED_SOURCE_NOT_PASS")
    source_cer = source.get("artifact", "")
    if source_cer == "RATE_CER079_END_OF_DAY_CLOSURE_EVIDENCE":
        trading_date = source["trading_date"]
        cadence = source["final_cadence_for_trading_date"]
        state_id = source["final_state_id"]
        state_hash = source["final_state_hash"]
        previous_state_id = (source.get("state_ids") or {}).get("12:00")
    else:
        raise RuntimeError("UNSUPPORTED_SEED_SOURCE_CER")
    if cadence != "19:30":
        raise RuntimeError("SEED_SOURCE_NOT_END_OF_DAY_1930")
    root = Path(artifacts_root)
    latest_path = root / "RATE_PRODUCTION_STATE_LATEST.json"
    dest = root / "production_state" / "live" / trading_date / "1930" / "RATE_PRODUCTION_PERSIST_RESULT_EVIDENCE.json"
    if latest_path.exists():
        existing_latest = load_json(latest_path)
        if existing_latest.get("validation_status") == "PASS" and existing_latest.get("current_state_id") and existing_latest.get("current_state_hash"):
            evidence = {
                "artifact": "RATE_PRODUCTION_LIVE_BOOTSTRAP_SEED_EVIDENCE",
                "validation_status": "PASS",
                "source_cer": source_cer,
                "source_state_id": state_id,
                "source_state_hash": state_hash,
                "source_trading_date": trading_date,
                "source_cadence": cadence,
                "destination_live_state_path": str(dest).replace("\\", "/"),
                "latest_path": str(latest_path).replace("\\", "/"),
                "idempotency_result": "BOOTSTRAP_NOT_REQUIRED_EXISTING_LIVE_STATE",
                "bootstrap_mode": False,
                "existing_live_state_preserved": True,
                "existing_latest_state_id": existing_latest.get("current_state_id"),
                "existing_latest_state_hash": existing_latest.get("current_state_hash"),
                "existing_latest_trading_date": existing_latest.get("trading_date"),
                "existing_latest_cadence": existing_latest.get("cadence"),
                "first_production_bootstrap_used": False,
                "persistent_state_reset": False,
            }
            if evidence_output:
                atomic_write_json(Path(evidence_output), evidence)
            return evidence
        raise RuntimeError("INVALID_LIVE_LATEST_ALREADY_EXISTS")
    payload = {
        "artifact": "RATE_PRODUCTION_LIVE_BOOTSTRAP_SEED_PERSIST_RESULT",
        "validation_status": "PASS",
        "source_cer": source_cer,
        "source_state_id": state_id,
        "source_state_hash": state_hash,
        "source_trading_date": trading_date,
        "source_cadence": cadence,
        "current_state_id": state_id,
        "current_state_hash": state_hash,
        "previous_state_id": previous_state_id,
        "persist_result": {
            "status": "SEEDED_FROM_ACCEPTED_EOD_STATE",
            "new_record_count": 1,
            "duplicate_record_count": 0,
            "state_entry": {
                "current_state_id": state_id,
                "decision_payload_hash": state_hash,
                "previous_state_id": previous_state_id,
                "previous_state_resolution": "FORMALLY_ACCEPTED_EOD_STATE_SEED",
                "trading_date": trading_date,
                "decision_time": "19:30",
                "cadence": "19:30",
                "execution_scope": "PRODUCTION",
            },
        },
    }
    idempotency = "SEEDED_NEW_RECORD"
    if dest.exists():
        existing = load_json(dest)
        if existing.get("current_state_id") != state_id or existing.get("current_state_hash") != state_hash:
            raise RuntimeError("INCOMPATIBLE_LIVE_SEED_ALREADY_EXISTS")
        idempotency = "IDEMPOTENT_NOOP"
    else:
        atomic_write_json(dest, payload)
    latest = {
        "artifact": "RATE_PRODUCTION_STATE_LATEST",
        "validation_status": "PASS",
        "trading_date": trading_date,
        "cadence": "19:30",
        "current_state_id": state_id,
        "current_state_hash": state_hash,
        "previous_state_id": previous_state_id,
        "live_state_evidence_path": str(dest).replace("\\", "/"),
        "source_cer": source_cer,
    }
    if latest_path.exists():
        existing_latest = load_json(latest_path)
        if existing_latest.get("current_state_id") not in (None, state_id) or existing_latest.get("current_state_hash") not in (None, state_hash):
            raise RuntimeError("INCOMPATIBLE_LIVE_LATEST_ALREADY_EXISTS")
    atomic_write_json(latest_path, latest)
    evidence = {
        "artifact": "RATE_PRODUCTION_LIVE_BOOTSTRAP_SEED_EVIDENCE",
        "validation_status": "PASS",
        "source_cer": source_cer,
        "source_state_id": state_id,
        "source_state_hash": state_hash,
        "source_trading_date": trading_date,
        "source_cadence": cadence,
        "destination_live_state_path": str(dest).replace("\\", "/"),
        "latest_path": str(latest_path).replace("\\", "/"),
        "idempotency_result": idempotency,
        "bootstrap_mode": True,
        "existing_live_state_preserved": False,
        "first_production_bootstrap_used": False,
        "persistent_state_reset": False,
    }
    if evidence_output:
        atomic_write_json(Path(evidence_output), evidence)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed live production state store from accepted CER-079 EOD state exactly once.")
    parser.add_argument("--source-evidence", required=True)
    parser.add_argument("--artifacts-root", default="artifacts")
    parser.add_argument("--evidence-output", default="artifacts/production_state/RATE_PRODUCTION_LIVE_BOOTSTRAP_SEED_EVIDENCE.json")
    args = parser.parse_args()
    evidence = seed(source_evidence_path=args.source_evidence, artifacts_root=args.artifacts_root, evidence_output=args.evidence_output)
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

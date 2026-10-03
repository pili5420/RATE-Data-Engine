from __future__ import annotations

from pathlib import Path
from typing import Mapping

from . import production_live_state


def load_phase_a_previous_state(
    *,
    state_root: str | Path | None,
    trading_date: str | None,
    cadence: str | None,
    expected_previous_state_id: str | None = None,
    expected_previous_state_hash: str | None = None,
    reference_path: str | Path | None = None,
) -> tuple[dict | None, list[str]]:
    if not state_root or not trading_date or not cadence:
        return None, ["MISSING_PREVIOUS_STATE"]
    try:
        loaded = production_live_state.load_live_state(state_root, trading_date, cadence)
        state = dict(loaded["state"])
        manifest = loaded["manifest"]
        if reference_path is not None:
            reference = Path(reference_path)
            if not reference.is_file():
                raise RuntimeError("MISSING_PREVIOUS_STATE")
            if production_live_state.file_hash(reference) != production_live_state.file_hash(loaded["path"]):
                raise RuntimeError("PREVIOUS_STATE_REFERENCE_MISMATCH")
        if expected_previous_state_id and state.get("current_state_id") != expected_previous_state_id:
            raise RuntimeError("PREVIOUS_STATE_ID_MISMATCH")
        if expected_previous_state_hash and state.get("decision_payload_hash") != expected_previous_state_hash:
            raise RuntimeError("PREVIOUS_STATE_HASH_MISMATCH")
        return {
            "current_state_id": state.get("current_state_id"),
            "decision_payload_hash": state.get("decision_payload_hash"),
            "previous_state_id": state.get("previous_state_id"),
            "previous_production_snapshot_id": _previous_snapshot_id(state, manifest),
            "canonical_manifest": manifest,
            "canonical_state": state,
        }, []
    except RuntimeError as exc:
        return None, [str(exc) or "LIVE_STATE_INVALID"]


def _previous_snapshot_id(state: Mapping[str, object], manifest: Mapping[str, object]) -> str | None:
    decision = state.get("decision") if isinstance(state.get("decision"), dict) else {}
    for source in (state, decision, manifest):
        value = source.get("production_snapshot_id") if isinstance(source, Mapping) else None
        if value:
            return str(value)
    return None
